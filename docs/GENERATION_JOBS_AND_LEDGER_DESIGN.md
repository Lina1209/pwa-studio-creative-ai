# PWA Studio — архитектура durable jobs и credit ledger

**Статус:** проектирование следующего этапа. Не является включённой очередью или биллингом.  
**Дата:** 22.11.2026  
**Цель:** определить безопасный контракт до добавления платной генерации и фоновых workers.

## 1. Что есть сейчас

- FastAPI имеет синхронные endpoints `POST /api/chat` и `POST /api/prompts`.
- AI-вызовы ограничены semaphore внутри одного процесса. Ограничение не распределённое и не переживает рестарт.
- `public.ai_usage` хранит best-effort телеметрию AI-вызовов. Это журнал себестоимости/usage, а не пользовательский баланс и не финансовый ledger.
- `record_ai_usage` вызывается после ответа провайдера и делает отдельный HTTP-запрос в Supabase. Запись может не состояться, а запрос может добавить до 5 секунд задержки. Поэтому её нельзя использовать для авторитетного списания.
- Платная генерация видео/изображений/аудио ещё не подключена. Нельзя считать существующие endpoints durable jobs.

## 2. Решение по модели выполнения

Использовать Postgres как источник истины о состоянии задания и Redis-backed worker queue как механизм доставки/ускорения. Очередь не должна быть единственным местом, где хранится задание.

Рекомендуемая последовательность:
1. API аутентифицирует пользователя и проверяет entitlement, параметры и content safety.
2. Сервер вычисляет quote из серверного versioned pricing catalog. Клиент не присылает доверенную цену.
3. В одной транзакции Postgres создаются generation job и credit hold с одним idempotency key.
4. После commit задание публикуется в очередь. Если публикация не удалась, outbox/reconciler повторно публикует committed job.
5. Worker атомарно захватывает job с lease, heartbeat и ограничением попыток.
6. Provider adapter запускает операцию. Сетевые вызовы выполняются вне транзакции БД.
7. Результат сначала загружается в private storage и проверяется (owner, MIME, размер, checksum, duration/metadata), затем job завершается.
8. В одной транзакции job переводится в terminal state, hold захватывается (capture) или освобождается (release), записываются usage/cost и audit metadata.
9. Клиент получает состояние из API/БД после refresh. SSE/WebSocket могут ускорять обновление, но не являются источником истины.

## 3. Таблицы и ключевые ограничения

### generation_jobs
Предлагаемые поля:
- `id uuid primary key`, `user_id uuid not null references auth.users`;
- `project_id uuid null`, `job_type text`, `provider text`, `model text`;
- `status` из фиксированного набора: queued, running, retry_wait, succeeded, failed, cancel_requested, cancelled, expired;
- `idempotency_key text not null`, уникальность `(user_id, idempotency_key)`;
- `request_hash` для запрета повторного использования одного ключа с другим содержимым;
- `request_snapshot jsonb`, `pricing_snapshot jsonb`, `result_asset_id uuid null`;
- `attempt_count`, `max_attempts`, `available_at`, `lease_owner`, `lease_expires_at`, `heartbeat_at`;
- `provider_job_id`, `last_error_code` (без секретов и сырого prompt), `created_at`, `updated_at`, `completed_at`.

Обязательные индексы: очередь по `(status, available_at, created_at)`, lease recovery по `(status, lease_expires_at)`, история владельца по `(user_id, created_at desc)`. Уникальный provider event ID хранить отдельно для webhook deduplication.

### credit_wallets
- Одна запись на пользователя и валюту/тип кошелька.
- Раздельные `available` и `reserved` значения.
- Неотрицательные ограничения на оба значения.
- Обновления только транзакционными server-side функциями с блокировкой строки `FOR UPDATE`.

### credit_holds
- Один hold на платную job, уникальный `job_id` и `idempotency_key`.
- Сумма, статус (held/captured/released/partially_captured), версия прайса и snapshot quote.
- Повторный capture/release должен быть безопасным и не менять баланс повторно.

### credit_ledger
- Append-only журнал: grant, reserve, capture, release, refund, adjustment, expiry.
- `idempotency_key` уникален в области операции.
- Записи содержат пользователя, job/hold, amount, currency, actor/source и безопасные metadata.
- Нельзя исправлять или удалять исторические строки; исправление — отдельная компенсирующая запись.
- Триггер запрещает UPDATE/DELETE; административные изменения — только отдельной audited-командой.

### outbox_events
- Создаётся в той же транзакции, что job/hold.
- Dispatcher отправляет событие в Redis и отмечает доставку.
- Повторная отправка допустима; worker обязан дедуплицировать по job ID/event ID.

## 4. Транзакционные правила

### Reserve
- Блокировать wallet row.
- Проверить достаточный available balance и актуальность quote.
- Перевести сумму из available в reserved.
- Создать hold и ledger reserve entry.
- Создать job и outbox event.
- Всё — одна транзакция. Любая ошибка откатывает все изменения.

### Capture
- Разрешён только при подтверждённом успешном сохранении результата.
- Перевести фактическую сумму из reserved в окончательное списание.
- Если фактическая стоимость ниже резерва, разницу вернуть в available.
- Если фактическая стоимость выше резерва, не списывать сверх согласованного максимума; завершить по утверждённой политике без скрытого дополнительного списания.

### Release
- Для отмены/ошибки до платной обработки вернуть весь hold в available.
- Если поставщик взимает плату за неудачный запрос, применить отдельно утверждённое правило; не маскировать provider cost как успешную пользовательскую генерацию.
- Все операции должны быть идемпотентны.

## 5. Состояния и восстановление

- `queued -> running` только через атомарный claim.
- `running -> retry_wait` только для временных ошибок и пока не исчерпаны попытки.
- `running -> succeeded` только после сохранения и проверки asset.
- `running -> failed` после исчерпания попыток/неповторяемой ошибки.
- `cancel_requested -> cancelled` после подтверждения отмены или безопасного завершения provider task.
- Истёкший lease возвращается в очередь reconciler-процессом; одновременно job не может принадлежать двум workers.
- Повторные webhooks дедуплицируются по provider event ID.
- Для provider без webhook используется polling с backoff и верхней границей срока ожидания.

## 6. Безопасность

- RLS: пользователь может читать только собственные jobs, wallet summary и ledger history.
- Клиент не может INSERT/UPDATE/DELETE jobs, holds, wallet или ledger напрямую.
- Все финансовые изменения выполняются backend service role через узкие SQL RPC функции.
- Service-role key никогда не попадает в frontend, логи, сообщения об ошибках или репозиторий.
- Job request snapshot не должен хранить секреты; чувствительные prompt/asset metadata ограничить политикой retention.
- Signed URLs короткоживущие; bucket private; storage path начинается с user UUID.
- Admin bypass не отменяет rate limits, provider budget и аудит.

## 7. Что пока нельзя утверждать/включать

- Redis/Celery не добавлены и не подключены к Render.
- Миграции `0009_generation_jobs_and_outbox.sql` и `0010_create_generation_job_rpc.sql` подготовлены в audit branch, но не применены к live Supabase. Их проверяет изолированный PostgreSQL 16 integration test.
- `generation_jobs` и `outbox_events` определены в миграции; backend-only RPC атомарно создаёт job + outbox event и поддерживает idempotent replay. SQL test проверяет owner isolation, client read-only permissions, отсутствие client execute permission, повтор запроса и единственность outbox event.
- Подготовлен backend service wrapper для trusted RPC и owner-scoped status reads; добавлен `GET /api/jobs/{job_id}`. Endpoint закрыт feature flag `GENERATION_JOBS_ENABLED`, который по умолчанию `false`; включение до применения и проверки миграций запрещено.
- Нет публичного `POST /api/jobs` (его контракт зависит от первого provider operation и серверной pricing policy), outbox dispatcher, worker process, provider webhook adapters или reconciler.
- Нет утверждённого денежного эквивалента кредита, финального прайс-листа, подписок и платёжного провайдера.
- Нельзя включать реальное списание, пока не пройдены race-condition, retry, webhook replay, worker-crash и two-account tests.

## 8. Порядок реализации

1. Сначала утвердить контракт job + asset и выбрать первый реальный provider/тип операции.
2. Подготовить и проверить SQL migrations для jobs/outbox, owner constraints, RLS и backend-only atomic creation RPC. (Schema/RPC подготовлены; live migration ещё не применена.)
3. Завершить backend API для создания job после выбора первой provider operation и server-side pricing contract. Owner-scoped status read уже подготовлен и feature-gated. Затем реализовать outbox dispatcher и worker deployment; добавить health checks, lease recovery и structured logs.
4. Добавить provider adapter для одной операции и тестовый fake provider.
5. Добавить wallet/hold/ledger RPC с транзакционными тестами и idempotency.
6. Только после подтверждения unit economics — включить pricing catalog и user-visible quotes.
7. Запустить пилот без публичных платежей, проверить расходы и fault recovery.
8. Отдельно провести юридическую проверку подписок, пакетов, возвратов и сроков действия кредитов.

**Ключевое правило:** Postgres хранит правду о job и деньгах; Redis только доставляет работу. Потеря Redis, перезапуск API или повтор webhook не должны приводить к потере проекта, двойной генерации или двойному списанию.

## 9. Idempotency boundary hardening (migration 0016)

The generic `create_generation_job_with_outbox` RPC now validates the allowed job type, bounded provider/model identifiers, idempotency-key length, a lowercase hexadecimal request hash, and object/size limits for request and pricing snapshots before inserting anything. A replay for the same `(user_id, idempotency_key)` returns the original job and original creation event; a replay with a different request hash, project, job type, provider or model is rejected. If a legacy job is found without its creation outbox event, the RPC repairs that missing event while holding the existing job row lock, rather than creating another job.

The isolated PostgreSQL integration test applies migration 0016 and checks first creation, exact replay, single outbox event, mismatched replay rejection, short-key rejection and malformed-hash rejection. This hardens job creation only. It does **not** guarantee exactly-once provider execution: a worker can lose its lease after the provider accepted a request, and a later worker may retry. The selected provider adapter must pass a stable provider idempotency token derived from the durable job ID when the provider supports it; otherwise the system must explicitly model ambiguous provider outcomes and reconcile/poll before issuing another billable request.

No credit wallet, hold, capture, release or ledger is introduced by this migration. There is no agreed credit price or billing policy yet, so no financial mutation is enabled. The future wallet hold and ledger must be created in the same transaction as job creation, with unique operation keys and row locking, after pricing and refund policy are approved.
