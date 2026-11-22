# PWA Studio — восстановление проектов и результатов после сбоев

**Статус:** кодовая реализация и изолированные CI-проверки; production-проверки не выполнялись.  
**Область:** локальные проекты Mini Movie Studio, их синхронизация с Supabase, durable generation jobs и приватные файлы результатов.

## 1. Принцип восстановления

- Локальный черновик и облачная копия — разные уровни защиты. Ошибка облака не должна удалять локальный черновик.
- Postgres является источником истины для состояния durable generation job и кредитных транзакций.
- Storage result считается готовым только после проверки приватного объекта, owner path, MIME, размера, содержимого и SHA-256.
- Повторные запросы должны быть идемпотентными. Неоднозначный ответ не является доказательством, что операция не состоялась.
- Восстановление по умолчанию read-only или повторяет безопасную операцию. Никакого автоматического удаления пользовательских проектов или файлов в recovery scanner нет.

## 2. Mini Movie Studio: потеря сети и перезапуск вкладки

1. Каждое изменение проекта записывается в account-scoped localStorage key до облачной синхронизации.
2. Для вошедшего пользователя синхронизация отправляет upsert с тем же project UUID; повторный upsert не создаёт новый проект.
3. Если Supabase недоступна, локальный черновик остаётся на устройстве. UI сообщает, что облачное сохранение не подтверждено.
4. Синхронизация повторяется с exponential backoff от 1 секунды до 5 минут. Загрузка облачных проектов повторяется отдельно, начиная с 2 секунд и с тем же верхним пределом.
5. При событии браузера online приложение запускает загрузку облака и немедленную попытку синхронизации. При возвращении вкладки в foreground запускается попытка отправить локальные изменения.
6. При следующем входе локальные проекты объединяются с облачными по project UUID и времени изменения. Локальные данные не удаляются из-за временной ошибки чтения облака.
7. Удаления хранятся как account-scoped tombstones. Они удаляются из очереди только после подтверждённого удаления в облаке.

### Граница гарантии

Сейчас локальное хранилище Mini Movie Studio — localStorage, а не IndexedDB. Очистка данных сайта, удаление браузерного профиля, нехватка места или потеря устройства могут уничтожить единственную локальную копию, если синхронизация с облаком ещё не завершилась. Не закрывайте приложение как «сохранённое в облаке», пока UI не подтвердил облачную синхронизацию. IndexedDB, экспорт/импорт резервной копии и полноценный конфликтный merge остаются отдельными задачами.

## 3. Смена аккаунта во время синхронизации

- Каждый цикл синхронизации фиксирует user UUID при старте.
- До последующих чтений/записей проверяется, что текущая сессия всё ещё принадлежит этому UUID.
- Локальные ключи проектов и tombstones включают user UUID.
- Запрос удаления дополнительно ограничен owner_id и project_type.
- Отложенный retry старого аккаунта не должен запускаться в сессии другого пользователя.

Для выпуска всё равно нужны ручные browser tests: аккаунт A изменяет проект, начинается медленная сеть, выполняется logout/login в аккаунт B, затем сеть восстанавливается. Проверить, что данные A не появляются в B и наоборот.

## 4. Generation job: Worker остановился или потерял lease

1. Worker получает job только через атомарный Postgres claim с lease.
2. Heartbeat продлевает только действующий lease владельца.
3. После истечения lease следующий Worker может безопасно забрать job. Старый Worker не может менять journal, heartbeat, retry, fail или completion.
4. Durable provider-operation journal и стабильный idempotency key позволяют восстановить состояние внешней операции.
5. Если provider lookup сообщает succeeded, используется существующий результат. Pending/unknown/недоступность приводит к ограниченному retry. Not-found разрешает повторную отправку только при подтверждённой provider-side idempotency. Иначе задача quarantined.
6. Для состояния result_received отрицательный или неопределённый lookup не разрешает повторную генерацию: сначала нужно восстановить исходный результат.
7. Результат загружается в deterministic owner/job path через create-only storage. При повторной загрузке существующий объект проверяется, а не перезаписывается.
8. Completion атомарно сохраняет storage path, SHA-256 и capture ledger entry. Потерянный ответ допускает только точный replay с тем же job, path и SHA-256.

Если provider не поддерживает надёжный lookup и idempotency, автоматическая безопасная повторная генерация не гарантируется. Такой provider нельзя подключать к production worker без отдельного recovery design.

## 5. Supabase недоступна или ответ потерян

- Ошибка чтения/записи облака не считается подтверждением отсутствия проекта или результата.
- Повторные RPC completion используют те же идентификаторы и контрольную сумму; база проверяет replay и не должна повторно списывать hold.
- Временная ошибка Storage при integrity scan попадает в deferred_checks, а не объявляется повреждением файла.
- Отсутствующий SHA-256 у старой succeeded job помечается как legacy/unverified; доверенная контрольная сумма задним числом не выдумывается.
- Несовпадение сохранённого SHA-256 и фактического объекта — integrity failure. Объект сохраняется для расследования, автоматическое удаление запрещено.

## 6. Что оператор может проверить

Использовать read-only методы/отчёты:
- job inventory: queued, active lease, expired/reclaimable lease, exhausted lease, retry_wait;
- provider operation journal: submitting, accepted, unknown, provider_failed, result_received;
- storage inventory: referenced objects, pending objects, orphan candidates, integrity warnings;
- result integrity report: verified results, integrity failures, deferred checks;
- credit hold/ledger: reserve, capture, release и соответствующий job ID.

Orphan candidate — только кандидат для последующего ручного review, не команда на удаление. Не удалять файлы, если inventory неполон, storage listing завершился ошибкой, job имеет неизвестный статус или владелец не подтверждён.

## 7. Что ещё не включено

- Production outbox dispatcher и Redis-backed queue deployment.
- Постоянный reconciler/cron для автоматического обхода jobs, outbox и Storage.
- Реальный provider adapter и его подтверждённые lookup/idempotency гарантии.
- Live end-to-end проверка двух аккаунтов и двух устройств.
- IndexedDB и экспортируемые резервные копии проектов.
- Автоматическое восстановление после очистки браузерного хранилища.

До завершения этих пунктов нельзя обещать production-grade disaster recovery. Текущие SQL и backend механизмы подготовлены и проверяются в изолированном CI; они не включают live generation.


## IndexedDB recovery mirror and manual project backups

The browser now loads `movie-storage.js` before the application and uses an account-scoped IndexedDB vault as an additional durable mirror for Mini Movie Studio projects and deletion tombstones.

- The synchronous `localStorage` path remains the compatibility cache and immediate fallback; IndexedDB writes are asynchronous and do not replace the cloud source of truth.
- Records are keyed by the current Supabase user UUID (or the separate guest scope). On startup and account changes, recovery reads only that scope and merges by project ID, keeping the newer `updatedAt`/ `createdAt` value.
- If IndexedDB is unavailable, blocked, or quota-limited, the app keeps the localStorage path and surfaces a degraded-mode message. It does not delete either copy.
- The Mini Movie Studio now offers JSON export/import. Backups contain project content and metadata only, never session tokens, API keys, or provider secrets. Account backups are bound to the originating user UUID; guest backups are separate. Import validates the format/size and merges by stable project ID without silently replacing a newer local version.
- Import currently does not restore cloud deletion tombstones, and this is not a full multi-device conflict-resolution protocol. A manual export should still be kept outside the browser; browser storage can be cleared or the device can be lost.
- This is an IndexedDB recovery mirror, not an immutable off-device backup. Cloud sync remains dependent on Supabase availability and RLS. No production deployment or live browser/device validation is implied by these code changes.
