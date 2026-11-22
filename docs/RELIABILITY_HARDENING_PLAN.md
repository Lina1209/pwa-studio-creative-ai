# PWA Studio — план надёжности и готовности к production

Дата: 22.11.2026

Этот документ разделяет уже существующие механизмы, новые защитные изменения и функции, которых пока нет. Никакой пункт не считается проверенным в production только потому, что для него создан код или SQL-файл.

## 1. Что изменено на текущем этапе

### Backend AI

- Добавлен настраиваемый предел одновременных AI-вызовов на один backend-процесс.
- Добавлено ограниченное время ожидания свободного слота. При переполнении backend возвращает HTTP 503 и заголовок `Retry-After: 10`, а не накапливает бесконечное число ожидающих потоков.
- Тайм-аут внешнего AI-запроса и число повторов вынесены в настройки окружения и валидируются.
- Освобождение слота гарантировано через `finally`, включая ошибки провайдера и пустые ответы.
- В health-ответ добавлено безопасное значение текущей ёмкости AI.
- Добавлены unit-тесты успешного ответа, отсутствующего ключа, перегрузки, пустого ответа и Ollama.
- GitHub Actions устанавливает dev-зависимости и запускает backend unit tests.
- Последний PR workflow после исправления `PYTHONPATH` завершился успешно: все шаги, включая backend unit tests, manifest validation и syntax checks, имеют статус success (run 45037292143).

### Целостность данных между владельцем и дочерними записями

- Подготовлена миграция `0008_enforce_child_owner_integrity.sql`.
- Она проверяет, что сообщения принадлежат владельцу диалога, а персонажи и сцены — владельцу проекта.
- После успешной preflight-проверки добавляются составные внешние ключи по паре (parent_id, user_id). Это переносит часть защиты с одних только RLS-политик на ограничения самой базы данных.
- При обнаружении старых несогласованных строк миграция останавливается с понятной ошибкой; автоматическое переназначение владельца не выполняется.
- Миграция подготовлена в ветке аудита, но не применялась к Supabase. Перед применением нужно выполнить резервное копирование и проверить данные в целевой базе.

### Важная граница

Текущий semaphore работает только внутри одного процесса. Он не является общей очередью между несколькими Render instances/workers и не переживает перезапуск. Это временная защита от перегрузки существующих AI chat/prompt endpoints, а не замена Redis/Celery и не очередь видеогенерации.


### Scene-bound generation API (prepared, fail-closed)

- Added migration `0012_create_scene_generation_job_rpc.sql`: one database transaction creates a scene-owned job and its outbox event. It validates scene ownership, request shape/size, and idempotency replay consistency.
- Added backend service `create_scene_generation_job` and authenticated endpoint `POST /api/scenes/{scene_id}/image-jobs`.
- The endpoint derives the owner from the verified Supabase access token; it never accepts a client-supplied user ID, provider, or model.
- The request validates prompt length, dimensions (multiples of 64), optional negative prompt, and seed. A canonical SHA-256 request hash binds the idempotency key to the scene, provider/model selection, and request.
- Submission is fail-closed. It returns HTTP 503 unless generation jobs are enabled, the durable worker is explicitly marked ready, and an image provider/model have been selected server-side. All readiness flags default to false/unset. No queued work is created while those prerequisites are absent.
- Added API tests for worker-not-ready, no-provider-selected, and invalid dimensions. Added PostgreSQL integration coverage for scene ownership, idempotency, and outbox atomicity.
- This is an API contract and guarded submission path, not a working image generator. The frontend is not yet wired to it; no worker, provider adapter, storage upload, webhook, or credit ledger is active.



### Atomic worker lifecycle primitives (schema/RPC only)

- Added migration `0013_generation_job_worker_lifecycle.sql`.
- `claim_next_generation_job` atomically claims one eligible job using `FOR UPDATE SKIP LOCKED`, increments its attempt count, and assigns a bounded lease. Expired leases can be reclaimed; exhausted jobs become terminal failures.
- `heartbeat_generation_job` extends only the unexpired lease owned by the named worker.
- `retry_generation_job` clears the active lease and schedules a bounded retry, or marks the job failed after its configured attempt limit.
- `complete_generation_job` accepts only the active lease owner and an owner-prefixed storage path. The worker must verify the uploaded object (private bucket, MIME, size, checksum and ownership) before calling it; the RPC does not independently inspect Storage.
- All four RPCs are executable only by `service_role`; authenticated clients cannot claim, heartbeat, retry or complete jobs.
- PostgreSQL integration tests cover exclusive claims, lease ownership, heartbeat, retry/reclaim, owner-scoped result paths and RPC grants.
- These are database lifecycle primitives, not a deployed worker. There is still no polling process, outbox dispatcher, provider adapter, storage uploader or live job execution. Feature flags remain disabled, and no provider has been selected.

## 2. Текущая функциональная реальность

В репозитории пока нет подключённого полноценного видеогенератора, монтажного timeline engine, FFmpeg pipeline, durable job queue, provider webhooks, S3/CDN asset pipeline или пользовательского биллинга с hold/capture/refund.

Миникиностудия сейчас сохраняет и редактирует планировочные данные/черновики. Поэтому нельзя честно заявить, что исправлены Safari playback, audio drift, GPU OOM или FFmpeg render errors: производственного видеопотока, на котором можно проверить эти случаи, пока нет.

Также пока не реализованы:
- IndexedDB как основное локальное хранилище проекта;
- автоматическое восстановление незавершённых upload/render jobs;
- распределённые лимиты AI по аккаунту и поставщику;
- долговечная очередь с retry/backoff/dead-letter;
- подписанные короткоживущие URL для будущих медиафайлов;
- транзакционный ledger кредитов и резервирование;
- end-to-end нагрузочные и межаккаунтные тесты.

## 3. Целевая архитектура очередей и генерации

Перед подключением любой платной генерации нужно создать отдельную сущность задания в базе данных. Браузер не должен удерживать долгий HTTP-запрос до окончания рендера.

Рекомендуемый жизненный цикл задания:

1. Backend проверяет пользователя, права, лимиты, формат запроса и moderation result.
2. В одной транзакции создаёт job с уникальным idempotency key и резервирует ожидаемую стоимость.
3. Worker получает job из Redis/Celery (или эквивалентной durable queue), фиксирует lease/heartbeat и запускает provider adapter.
4. Retry допускается только для временных ошибок; применяется exponential backoff с jitter, пределом попыток и dead-letter состоянием.
5. Webhook проверяется по подписи провайдера и дедуплицируется по event ID. Если webhook потерян, периодический reconciler опрашивает provider status и восстанавливает состояние.
6. После получения результата backend проверяет наличие файла, размер, MIME, checksum и метаданные, сохраняет его в private storage и только затем завершает job.
7. Только после подтверждённого сохранения результата резерв конвертируется в списание. При отмене/ошибке резерв освобождается согласно правилам поставщика.
8. Клиент восстанавливает статус после перезагрузки через GET job status. WebSocket/SSE — ускорение обновления, но не единственный источник истины.

Обязательные статусы: `queued`, `running`, `retry_wait`, `succeeded`, `failed`, `cancel_requested`, `cancelled`, `expired`. Переходы должны быть атомарными и проверяться на сервере.

## 4. Биллинг без двойных списаний

До включения платных операций нужен ledger, а не один редактируемый баланс:

- уникальный idempotency key на пользовательскую операцию;
- атомарный hold/reserve до постановки задания в очередь;
- capture только после успешного сохранения и проверки результата;
- release/refund при ошибке, отмене или истечении задания;
- защита от повторных webhook, повторной отправки формы и параллельных запросов;
- неизменяемые записи ledger и аудит ручных корректировок;
- запрет отрицательного баланса и повторного capture одного hold;
- явная оценка стоимости до старта и возврат неиспользованного резерва.

Нельзя списывать кредиты на основании одного ответа provider API: сначала нужно проверить, что конечный файл действительно доступен и принадлежит текущему пользователю.

## 5. Медиа, FFmpeg и совместимость браузеров

Для будущего рендера следует зафиксировать единый профиль экспорта и проверять его через ffprobe:

- MP4 container, H.264 video, AAC audio;
- постоянная частота кадров (например, 30 fps) и согласованный timebase;
- нормализованные размеры и pixel format;
- корректные timestamps/PTS/DTS, длительность и sample rate;
- ресемплинг/сведение аудио и проверка A/V sync;
- aspect ratio 16:9, 9:16 или 1:1 задаётся в job metadata и проверяется после рендера;
- оригиналы и прокси хранятся отдельно; исходники не перезаписываются.

Для Safari/iOS нужен реальный тестовый набор устройств. MIME type, кодек и расширение файла должны соответствовать друг другу. Проверять надо не только воспроизведение в браузере, но и скачанный MP4 в системном плеере.

## 6. Frontend: сохранение состояния и память

Когда в приложении появится настоящий timeline/media editor, обязательны:

- IndexedDB для локальных snapshots и больших данных; localStorage оставить для небольших настроек;
- debounce автосохранения примерно 5 секунд, немедленный flush при уходе со страницы/переходе в background;
- индикатор `Сохранено / Сохраняю / Нет сети / Есть несинхронизированные изменения`;
- revision/version для обнаружения конфликтов, а не тихая перезапись более новой версии;
- очередь отложенной синхронизации с повторами после восстановления сети;
- очистка всех `URL.createObjectURL` при замене/удалении media source и закрытии проекта;
- освобождение `MediaSource`, `MediaStream`, audio nodes, event listeners, timers и observers;
- ограниченные proxy previews, виртуализация длинного timeline и ленивое чтение медиа;
- проверка утечек по heap snapshots при длительной работе.

Проверка должна включать обновление страницы, закрытие/повторное открытие вкладки, 10-секундное отключение сети и смену аккаунта во время сохранения.

## 7. Обязательные тесты перед запуском

### Автоматические
- unit tests на состояния job, retries, idempotency, ledger hold/capture/release;
- integration tests с тестовым provider adapter и тестовым object storage;
- SQL/RLS tests на владельца проекта, job, ledger и asset;
- нагрузочные тесты очереди с несколькими пользователями и ограниченной concurrency;
- fault injection: timeout, 429, 5xx, потерянный webhook, повторный webhook, worker crash, storage upload failure;
- FFmpeg golden tests для длительности, размеров, codec, аудио и A/V sync.

### Ручные browser/device
- Chrome Android и desktop, Safari macOS и iPhone;
- 16:9, 9:16, 1:1;
- длительная работа timeline, смена сцен и очистка памяти;
- offline/online, refresh во время job, восстановление после закрытия браузера;
- скачивание итогового файла и открытие в системном плеере.

### Безопасность и биллинг
- 10–20 одновременных jobs с разных аккаунтов;
- подтверждение отсутствия межаккаунтного доступа к проектам, job и файлам;
- отключённый/неверный API key не уменьшает баланс;
- повторный запрос и повторный webhook не создают двойное списание;
- отказ moderation возвращает понятную причину и не оставляет вечный loader.

## 8. Критерий готовности

Не объявлять PWA Studio готовой к публичному запуску, пока не пройдены автоматические тесты, реальные тесты на двух аккаунтах, проверка RLS/Storage, fault-injection и тесты на поддерживаемых устройствах. Для каждой интеграции хранить evidence: дата, среда, версия, сценарий, результат и ссылка на лог/артефакт.

Ни один программный проект нельзя гарантированно сделать «без единого сбоя». Цель — предотвратить известные классы ошибок, обнаруживать сбои, безопасно восстанавливаться и не терять проекты/деньги/приватные данные.


## 9. Outbox delivery lifecycle primitives (schema/RPC only)

Migration `0014_outbox_delivery_lifecycle.sql` adds bounded delivery attempts, worker leases, and a terminal dead-letter timestamp to `outbox_events`. The service-role-only RPCs are:

- `claim_next_outbox_event`: atomically leases one due event with `FOR UPDATE SKIP LOCKED`; expired leases can be reclaimed while the attempt budget remains.
- `mark_outbox_event_published`: acknowledges delivery only for the active, unexpired lease owner.
- `retry_outbox_event`: releases the active lease and schedules a bounded retry, or sets `failed_at` after the configured attempt limit.

The PostgreSQL integration suite verifies event ownership, competing workers, acknowledgement, retry, and dead-letter behavior. These are database primitives, not a running dispatcher: no broker delivery, polling process, monitoring, or production migration is enabled. A future dispatcher must publish idempotently and tolerate the unavoidable crash window between broker acceptance and recording `published_at`; consumers should deduplicate by the stable `event_id`.


## 10. Explicit terminal failure for generation workers (schema/RPC only)

Migration `0015_generation_job_terminal_failure.sql` adds `fail_generation_job(job_id, worker_id, error_code)`. It is intentionally distinct from `retry_generation_job`: permanent provider/configuration/validation failures can move directly to `failed` instead of being retried until the attempt budget is exhausted.

The function:
- accepts only a bounded, normalized error code (never raw provider text);
- requires the caller to own the active, unexpired worker lease;
- clears lease and heartbeat fields and sets the terminal timestamp;
- refuses subsequent heartbeat, retry, or completion transitions;
- is executable only by `service_role`.

The PostgreSQL integration suite verifies the active-owner requirement, terminal metadata, and rejection of later transitions. This is still a database primitive: no worker runtime, provider adapter, storage uploader, or production migration is deployed. The generation submission feature flag remains disabled.


## 11. Generation result storage verification contract (unit-tested, adapter not connected)

Added backend module `generation_result_storage.py` with a strict, provider-neutral validation boundary. Before a worker may mark an image job successful, the future storage adapter must supply authoritative metadata for the uploaded object. The validator checks:

- exact configured bucket and exact object path;
- owner UUID as the first path segment and rejection of traversal, empty segments, absolute paths, and backslashes;
- explicit private-bucket confirmation;
- allowlisted image MIME type and bounded non-zero size;
- canonical SHA-256 checksum equality with the bytes prepared for upload.

The module returns a small verified-asset value and safe error codes; it does not expose object contents, credentials, or provider messages. Unit tests cover valid metadata and rejected bucket, path, privacy, MIME, size, checksum, and empty-payload cases.

This is a validation contract only. It does not upload to Supabase Storage, independently query bucket privacy, or run a worker. The future adapter must fetch bucket/object metadata from Supabase itself; it must never construct the metadata from client-supplied values.
