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

## 18. Recovery after provider result receipt

The provider-operation journal's `result_received` state is a durable checkpoint, not a copy of the generated image bytes. If a worker crashes after recording this checkpoint but before the private Storage upload and job completion, a replacement worker must retrieve the complete image payload through the provider's lookup-by-idempotency-key operation. A provider request ID alone is insufficient.

For a journal already in `result_received`:
- a successful lookup may resume validation, private upload and job completion;
- pending, unknown, unavailable or not-found lookup results schedule bounded retry without changing the journal state;
- the worker must never submit a new generation for that job, even if the provider reports not-found;
- the provider adapter must retain/retrieve the original result for the full application recovery horizon, or a future durable result-staging mechanism must be implemented before production use.

The current worker contract expects lookup success to return the complete `ImageGenerationResult` including image bytes. No real provider adapter has been registered or tested, so this recovery guarantee remains conditional on the chosen provider's documented lookup consistency, result availability and retention behavior. The worker runtime remains disabled by default.



## 19. Stale-worker guard around journal RPCs

The worker heartbeat can detect lease loss while a short database journal RPC is still in flight. Database RPCs independently validate the active lease, but the worker must also check its local lease-loss signal after the RPC returns: a successful journal-begin response that arrives late must never authorize a provider submission from a stale worker. The same rule applies after provider-acceptance and result-received journal transitions, and immediately before job completion.

The worker now exits with a lease-lost outcome at these boundaries. A replacement worker owns recovery through the durable journal and stable provider idempotency key. Tests cover lease loss while journal creation is delayed and while provider acceptance is delayed; both assert that no later provider/result/storage/completion work is started. These are deterministic fake-adapter tests; they do not replace integration testing against a live provider or Supabase deployment.


## 20. Bounded pagination during Storage verification

Generated-object verification must not assume the target file is among the first 100 objects in an owner's generated folder. Upload verification now scans bounded pages of 100 entries (up to 10 pages) for the deterministic owner/job filename. A truncated inventory produces a retryable adapter error rather than a false missing-object or integrity failure. A missing listing entry is also treated as retryable because Storage listing visibility may lag a successful create-only upload. The retry preserves the object; it does not overwrite or delete an object whose verification is incomplete.

The page cap is intentional: worker memory and request volume remain bounded. If the owner's folder exceeds the scan window and the target is not found, the job retries rather than declaring success or deleting data. Tests cover a target on the second page and the bounded-inventory case.


Completed-result integrity scans use the same bounded pagination policy as upload verification: 100 entries per page, up to 10 pages, stable created_at ordering. A truncated scan or temporarily missing listing entry is deferred as retryable Storage uncertainty, not reported as corruption. Only after metadata is found are MIME, size, privacy and downloaded bytes checked. The scan remains read-only and never changes a succeeded job or deletes its result.


## 21. Worker restart after an ambiguous provider response

If a provider accepted a generation request but the worker lost the response, the worker records the operation as unknown before scheduling retry. A restarted worker reclaims the same durable job, reads the existing provider-operation journal, and performs lookup with the stable job UUID idempotency key. If the provider reports success, the worker reuses that result and continues through result journaling, private Storage verification and job completion. It does not issue a second independent generation request. This behavior is covered by a two-worker-instance recovery test; the test uses fakes and does not establish any real provider's idempotency or lookup guarantees.


## 22. Database connectivity loss and worker transition policy

The Supabase worker repository adapter classifies timeouts and connection failures as retryable, HTTP 408/425/429 and 5xx responses as transient, and rejected credentials or other ordinary 4xx responses as permanent configuration/request failures. Error messages exposed to worker logic contain only normalized error codes; upstream response bodies, host details and credentials are not copied into them. The worker schedules bounded retries for transient repository failures and stops generation on permanent credential rejection. If a heartbeat cannot confirm lease ownership, the worker cancels in-flight provider/storage work and lets the database lease lifecycle recover the job; it must not continue external work on an unconfirmed lease.


## 26. Financial ledger implementation gate and acceptance criteria

The ledger remains a design only. Do not add a mutable client balance or connect payment collection until the following invariants are implemented and proven in the disposable PostgreSQL integration suite.

### Authoritative operation boundary

- A single server-side RPC must create the generation job, its outbox event, the wallet reservation, the hold, and the corresponding ledger entry in one database transaction. The existing job-creation RPCs do not yet reserve credits; do not call them a paid submission path.
- The backend derives the authenticated owner from the verified session. The client may provide an idempotency key, but never a user ID, wallet ID, amount, price, provider cost, or final charge.
- The server calculates a versioned quote from a server-owned pricing catalog and stores an immutable quote snapshot on the job/hold. The quote includes the maximum authorized charge, credit unit, price version, operation type, and relevant quantity/duration parameters.
- A replay with the same owner and idempotency key plus the same canonical request and quote returns the original job and hold. Any changed request or pricing identity is rejected without changing balances.

### Ledger and wallet invariants

- Ledger entries are append-only. A correction is a new compensating entry; historical entries are never edited or deleted.
- Wallet available/reserved totals are changed only inside trusted SQL RPC transactions while the wallet row is locked. Enforce non-negative balances with database constraints as well as guarded arithmetic.
- Every financial operation has a stable, unique operation key scoped to its operation type and hold. A repeated reserve, capture, release, refund, or adjustment must return the original outcome and must not apply the balance delta twice.
- A hold can transition only once from held to captured or released. Capture and release race tests must prove that only one terminal transition wins.
- Capture is permitted only after the job's verified asset is durably recorded and the job is eligible for success. Job completion, hold capture, wallet movement, and ledger append must commit atomically.
- Release is permitted only after a terminal failure/cancellation/expiry policy is satisfied. A retryable job must retain its hold; it must not release and reserve again on every worker retry.
- If actual provider cost exceeds the user-approved maximum, do not silently debit more credits. Apply an explicit, pre-approved policy and record provider cost separately from the user charge.
- Expiry and refunds require explicit policy and audited server-side operations. Never expire credits or refund based only on a browser event.

### Required adversarial integration tests before enabling billing

1. Two concurrent reservations against one wallet cannot overspend it.
2. Concurrent duplicate submissions with the same idempotency key create one job, one outbox event, one hold, and one reserve ledger entry.
3. Reusing the key with a different request or price snapshot is rejected without a financial mutation.
4. Repeated capture/release calls do not change balances or append duplicate operation entries.
5. Capture racing release has exactly one winner and leaves wallet/hold/ledger mutually consistent.
6. A worker crash before result verification cannot capture credits; retry retains the original hold.
7. A verified successful result and capture either both commit or both roll back.
8. A terminal failure releases the hold once; a later duplicate webhook or worker retry cannot release it again.
9. RLS prevents one user from reading another user's wallet, holds, or ledger; authenticated clients cannot mutate any of them or execute financial RPCs.
10. Ledger totals reconcile to wallet balances after grants, reserves, captures, releases, refunds, and adjustments.

### Activation gate

Keep billing, payment collection, credit deductions, and any public paid-generation endpoint disabled until pricing/unit economics, refund/cancellation rules, provider billing behavior, and legal terms are approved; all adversarial SQL tests pass; and a two-account end-to-end test has evidence. This document and the existing job/provider migrations do not implement a wallet or ledger and must not be presented as active billing.


## 27. Credit ledger schema foundation (migration 0018; not active billing)

Migration `0018_credit_ledger_schema.sql` introduces only the database structures needed for a future credit ledger:

- `credit_wallets`: one owner-scoped balance projection per user, with non-negative available and reserved credit counters.
- `credit_holds`: one quote-backed hold per generation job, with an explicit held/captured/released state and owner-matched composite foreign key.
- `credit_ledger`: append-only operation history with unique owner-scoped operation keys, balance-after snapshots, bounded metadata and owner-matched hold reference.
- RLS lets authenticated users read only their own rows. Authenticated clients have no insert/update/delete privileges; trusted service role has table privileges.
- A database trigger rejects UPDATE and DELETE against ledger history, including accidental privileged application writes. Corrections must be represented by compensating entries.

The migration deliberately does not create wallet mutation RPCs, grant/adjustment workflows, reserve/capture/release logic, payment integration, price catalog, or a paid submission endpoint. It does not initialize users with credits or alter any existing balance. Existing job creation remains separate and must not be treated as an atomic paid submission.

The disposable PostgreSQL integration script now applies migration 0018 and checks wallet creation, owner-matched hold constraints, ledger append-only behavior, and the absence of client mutation privileges. The CI run must pass before this schema is considered validated. Next implementation step is a single transaction boundary for paid job creation + outbox + wallet hold + reserve ledger entry, followed by lease-safe atomic completion/capture and terminal release RPCs. Do not apply this migration to production or enable billing until those RPCs and concurrency tests are complete.
