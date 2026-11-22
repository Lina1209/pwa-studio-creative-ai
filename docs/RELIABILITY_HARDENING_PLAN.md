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


## 12. Provider-neutral worker execution and Supabase RPC adapter (tested foundation)

Added `generation_worker.py`, an injected execution coordinator for one already-claimed image job:

- starts and maintains a lease heartbeat while generation and storage upload are running;
- cancels in-flight work if the lease is lost, and never marks the job complete afterward;
- validates the job payload and checks provider/model identity against the server-selected job;
- classifies provider errors into retryable versus terminal paths, with bounded exponential retry delay;
- validates private, owner-scoped storage metadata before completion;
- binds the uploaded object's reported checksum, MIME type and byte count to the exact generated bytes;
- records only safe error codes in job transitions.

Added `supabase_generation_worker_repository.py`, a service-role-only PostgREST adapter for claim, heartbeat, retry, terminal failure and completion RPCs. It accepts only server-side Supabase credentials, uses the `apikey` header for new secret keys and adds Authorization only for legacy JWT service-role keys. HTTP and response-shape failures are sanitized.

Tests use fake provider/storage adapters and HTTPX MockTransport. They cover success, permanent and retryable provider failures, provider/model mismatch, public object rejection, checksum mismatch, rejected completion, lease loss/cancellation, empty queue, malformed claim response and service-key handling.

**Deployment boundary:** this is an execution coordinator and database RPC adapter, not yet a continuously running worker process. There is no production provider, real Storage SDK adapter, polling loop, outbox dispatcher, worker deployment or enabled feature flag. We are deliberately not choosing Redis versus Postgres polling in code without recording and reviewing that architecture decision. The worker readiness flag and generation submission remain disabled.


## 13. Controlled worker polling runtime (tested, not deployed)

Added `generation_worker_runtime.py`:

- polls the database claim RPC using the configured worker identity and lease duration;
- processes one claimed job at a time per runtime instance, avoiding unbounded local task creation;
- uses bounded idle polling with exponential idle backoff and a separate bounded error backoff;
- logs safe job outcome metadata, not prompts, credentials or provider response bodies;
- supports graceful stop: stop claiming new work and let the active job finish with its heartbeat;
- leaves abrupt process termination to database lease expiry/reclaim logic;
- never fabricates a completion or retry transition after an unhandled runtime exception.

Added disabled-by-default settings for runtime enablement and bounded polling/error intervals, plus unit tests for disabled mode, claims, errors, stop requests and configuration validation.

**Not yet production-ready:** no composition root constructs the real provider and private Storage adapters; no deployed worker process, health supervision, external shutdown hook, distributed concurrency setting, queue-depth monitoring, or reconciliation/cleanup for orphaned uploads exists. The runtime is sequential per process; multiple processes rely on the database's `SKIP LOCKED` claim RPC. Keep `generation_worker_runtime_enabled=false`, `generation_job_worker_ready=false`, and `generation_jobs_enabled=false` until the missing adapters and deployment controls pass integration testing.


## 14. Real Supabase private image Storage adapter (HTTP integration contract)

Added `supabase_private_image_storage.py`, using Supabase Storage's documented REST endpoints and an injected HTTPX async client:

1. validates the generated bytes, supported image MIME and 20 MiB bound;
2. uploads with create-only semantics (`POST`, `x-upsert: false`) to `{owner_uuid}/generated/{job_uuid}.{ext}`;
3. reads the bucket configuration and fails closed unless `public=false`;
4. lists the exact owner-scoped folder and requires exactly one matching object metadata row;
5. validates stored size and MIME against the bytes being uploaded;
6. downloads the object through the authenticated private-object endpoint using a streaming 20 MiB cap;
7. compares the downloaded bytes byte-for-byte with the generated payload and computes SHA-256 from the downloaded bytes;
8. returns the verified metadata contract consumed by the worker before its database completion RPC.

If post-upload verification fails, the adapter attempts to delete only the exact owner/job object it just created. Cleanup failure is logged without exposing paths, prompts, keys or provider data; a future reconciler is still required for orphan cleanup.

The adapter supports new Supabase secret API keys through `apikey` and legacy JWT service-role keys through both `apikey` and `Authorization: Bearer`. The service-role key remains server-only. Bucket and request timeout settings are validated and bounded.

Tests use HTTPX MockTransport and cover create-only upload, private-bucket enforcement, authoritative metadata lookup, downloaded-byte equality, checksum, cleanup, missing metadata, size cap, and both service-key formats.

**Limitations / deployment gate:** tests are mocked; no live Supabase project has been contacted. Bucket `studio-media` must already exist, be private, and have the intended 20 MiB limit and image MIME allowlist. The worker runtime and job submission remain disabled. Before production, run a dedicated staging integration test against a non-production Supabase project, verify the exact Storage API response shape for the deployed Supabase version, test cleanup/reconciliation and confirm the storage bucket policies. Do not apply migrations or enable the worker as part of this change.


## 15. Read-only Storage recovery inventory and orphan planning

Added a bounded owner-scoped recovery scan:

- Storage adapter lists only `{owner_uuid}/generated`, first verifying that the configured bucket remains private.
- Storage listing is paginated with bounded page size/page count. Reaching the page cap is an error, never a partial-success result.
- Job repository reads only the same owner's generation job rows through service-role PostgREST, with bounded pagination and strict response validation.
- Recovery planner correlates UUID-based object names with job records and classifies objects as:
  - referenced: a succeeded job points to the exact object path;
  - pending: job is active/retryable or object/job is still within the grace period;
  - orphan candidate: no corresponding job exists, or the corresponding job is terminal failed/cancelled/expired, and both object and terminal job are older than the grace period (default seven days);
  - integrity warning: succeeded job path mismatch, invalid timestamp/name, foreign path, or unknown state.
- Duplicate inventory rows, incomplete pagination, malformed metadata, and invalid timestamps fail closed or are preserved as warnings.

**No deletion is implemented.** The scanner produces a report only. It deliberately preserves succeeded assets, live jobs, recent objects, unknown statuses and ambiguous records. A later cleanup operation must require a separately reviewed report, re-check the exact job and object immediately before deletion, enforce a second grace window, and write an audit record. There is no scheduled scanner, no production credentials used, and no live Supabase scan performed.

Tests cover successful result preservation, old missing-job objects, terminal-job orphans, live/recent preservation, mismatched success paths, unknown states, malformed timestamps, duplicate inventory and pagination caps.

## 16. Re-verification of previously stored generation results

The private Storage adapter now exposes a read-only `verify_existing_image` operation for a known owner/job/path tuple. It:

- rejects paths that do not exactly match the owner UUID, job UUID and supported image extension before making a request;
- independently confirms the configured bucket is still private;
- retrieves the exact object's Storage metadata and checks its MIME type and bounded size;
- downloads the object through the authenticated private endpoint with the existing hard byte limit;
- checks downloaded byte count against Storage metadata and calculates a fresh SHA-256 digest.

This provides a way for a future reconciler to detect missing, inaccessible, oversized or metadata-inconsistent results after a restart. It does not mutate the job, repair a file, delete an object, or automatically re-run generation. The verification listing is deliberately bounded and fails closed when its first page is full, rather than incorrectly treating an object beyond that page as missing.

Unit tests use HTTPX MockTransport and cover a valid private result, cross-owner/job path rejection, size mismatch and public-bucket rejection. No live Supabase request has been made. The adapter method is not yet called by a scheduled reconciler or user-facing API.

## 17. Read-only reconciliation of succeeded generation jobs

Added `verify_owner_succeeded_results`, which loads the bounded owner-scoped job inventory and re-verifies every succeeded job that declares a result path using the private Storage adapter. The report separates:

- verified result paths;
- integrity failures, including a succeeded job without a result path or a definitive metadata/content validation failure;
- deferred checks caused by retryable Storage transport/service errors.

Only expected Storage validation/adapter exceptions are classified. Unexpected programming errors propagate rather than being silently hidden. Non-succeeded jobs are not altered or retried. This is a report-only service: it does not update job status, recreate missing files, trigger generation, change credits, delete objects, or expose any service credentials. Tests cover success, corrupt data, missing path, temporary failure, and propagation of unexpected errors.

## 18. Read-only worker lease and retry recovery report

The owner-scoped generation-job inventory now also reads `lease_expires_at`, `attempt_count`, `max_attempts`, `available_at` and `last_error_code`, validating bounded counter values and metadata types. Pagination uses stable job-ID ordering so changing `updated_at` values do not reshuffle pages during a scan.

`plan_generation_job_recovery` classifies running jobs with active leases, expired leases that remain retryable, expired leases whose attempts are exhausted, queued jobs, ready/delayed retry-wait jobs, and malformed/unknown states. It is strictly read-only. The existing database `claim_next_generation_job` RPC remains the only authority that atomically reclaims an expired lease using `FOR UPDATE SKIP LOCKED` or marks an exhausted expired job failed. The report does not reset leases, increment attempts, invoke providers, or modify credits. Tests cover each classification and missing lease/schedule metadata.

Important operational distinction: an expired lease is eligible for atomic reclaim, not proof that the old worker has stopped executing. Worker-side cancellation and provider idempotency remain necessary; downstream provider requests must tolerate duplicate delivery after process pauses or network partitions.
