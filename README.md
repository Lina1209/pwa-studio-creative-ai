# PWA Studio — Creative AI

Творческая веб-студия для разработки видеоидей и кинопроектов.

## Текущая архитектура

- **Frontend:** Vanilla JavaScript, HTML and custom CSS; публикация через GitHub Pages.
- **Backend:** Python 3.12, FastAPI, LiteLLM; отдельное развёртывание через Render.
- **Authentication:** Supabase Auth; frontend использует только публичный publishable key.
- **Database / Storage:** Supabase Postgres and private Storage. Mini Movie Studio uses local-first drafts with Supabase synchronization to `public.projects`; migration `0005_cloud_projects_and_storage.sql` was applied and the table, owner policies, and private `studio-media` bucket were verified. Cross-device sync, conflict handling, and deletion synchronization still require end-to-end testing. Media upload UI is not implemented yet.

## Что уже реализовано

### Frontend
- Адаптивная PWA-оболочка, мобильная навигация, светлая и тёмная темы.
- Разделы студии: главная, создание видео, Миникиностудия, Prompt Studio, медиатека, голосовая мастерская, сценарий и сцены, AI Companion, личный кабинет, путеводитель и правила.
- Supabase sign-in, sign-up and password reset request.
- Mini Movie Studio: создание локальных черновиков, компактный список, редактирование параметров, копирование проекта, удаление с подтверждением, история версий и последовательные этапы сценария, персонажей, голосов и плана монтажа.
- Черновики Миникиностудии сохраняются локально и автоматически синхронизируются с `public.projects` после применения миграции 0005; облачное сохранение и синхронизация между устройствами пока ожидают проверки в live Supabase.

### Backend
- FastAPI health endpoint.
- JWT verification against Supabase JWKS.
- Authenticated AI Companion and prompt-generation endpoints with PostgreSQL-backed per-user rate/concurrency admission.
- LiteLLM adapter supports DeepSeek (default) and Google Gemini as an explicitly selected alternative. No automatic provider fallback is performed.
- AI admission is fail-closed and enforced in PostgreSQL across backend replicas: default ceilings are 10 requests/minute and 100 requests/rolling 24 hours per user, 2,000 requests/rolling 24 hours globally, plus per-user/global concurrency caps. Values are server-configurable through `AI_MAX_REQUESTS_PER_DAY_PER_USER` and `AI_MAX_REQUESTS_PER_DAY_GLOBAL`.
- Request-count ceilings are separate from the monetary controls. Each synchronous AI call now reserves a conservative worst-case USD amount in PostgreSQL before the provider request. The transaction serializes global and per-provider budget checks across backend replicas, then settles from returned token counts. Unknown outcomes retain their full reserve; timeouts never auto-release possible charges.
- Initial database guardrails in migration `0050_sync_ai_provider_cost_reservations.sql`: DeepSeek `$1.00` per UTC day, Gemini `$1.00` per UTC day, combined `$2.00` per UTC day, and `$0.50` maximum outstanding reservations. The administrator panel shows settled estimates, active reserves, unknown outcomes and remaining limits.
- Reservation prices use conservative peak paid-tier token rates plus a 25% margin: DeepSeek Flash `$0.30/$1.20` per million input/output tokens; DeepSeek V4 Pro `$1.32/$3.96`; Gemini 3.1 Flash-Lite `$0.25/$1.50`. Sources: [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) and [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing). Update the server price table when provider rates change. Gemini is estimated at paid-tier rates; Free Tier eligibility is never assumed.
- This is an atomic estimated-spend guard, not a provider invoice cap. Provider pricing changes, taxes, provider-side retries or incomplete usage metadata can still differ from estimates. Set independent spending limits in provider consoles and reconcile actual invoices. Optional `AI_DAILY_BUDGET_USD_DEEPSEEK` / `AI_DAILY_BUDGET_USD_GEMINI` remain warning thresholds in the usage report, not enforcement controls.
- Apply migration `0050` before enabling synchronous AI in a deployed environment. If the budget tables or RPCs are unavailable, AI calls fail closed before contacting the provider. No automatic provider fallback is enabled.
- Initial text safety checks. This is not full multimodal moderation.

## Важные ограничения

- Синхронизация проектов зависит от применения `supabase/migrations/0005_cloud_projects_and_storage.sql`; до проверки миграции и теста на втором устройстве не считайте облачную синхронизацию подтверждённой.
- AI-сценарист внутри этапов Миникиностудии, генерация изображений/видео, клонирование голоса, timeline editor and MP4 rendering are not connected yet. The stage editor currently saves and edits production notes/text locally.
- История версий хранится вместе с локальным проектом в браузере; очистка данных браузера может удалить её.
- AI endpoints require a deployed backend, valid Supabase URL, provider credentials and a signed-in session.
- A service worker provides offline shell fallback. Core HTML/JS/CSS assets use network-first updates with cached fallback.
- Supabase migration files are source-of-truth drafts; do not rerun old migrations blindly against an already configured live project.

## Product and implementation plans

The working source of truth and product requirements are maintained in:

- [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md) — completed, in-progress and remaining work with evidence labels.
- [Architecture, safety and product plan](docs/ARCHITECTURE_SECURITY_AND_PRODUCT_PLAN.md) — security, privacy, rights, moderation, quotas and release gates.
- [Support and feedback design](docs/SUPPORT_AND_FEEDBACK_DESIGN.md) — private user-to-administration inbox, feedback intake and future support widget.
- [Creator showcase and multimodal roadmap](docs/CREATOR_SHOWCASE_AND_MULTIMODAL_ROADMAP.md) — inspiration gallery, opt-in creator works, audio, speech, voice and video.
- [Provider idempotency audit](docs/PROVIDER_IDEMPOTENCY_AUDIT_2026-11-23.md) — current production-provider blockers and retry-safety requirements.

Important: review-branch code and passing CI do not mean a feature is deployed. Database migrations must be reviewed, applied and verified separately in the live Supabase project.

## Локальный запуск backend

Требуется Python 3.11+.

```bash
cd backend
python -m venv .venv
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Заполните `.env` локальными значениями. Не публикуйте Supabase service-role key или ключи AI-провайдера.

## Развёртывание

- Frontend: GitHub Pages, ветка `main`, каталог `/(root)`.
- Backend: Render Blueprint из `render.yaml`.
- Укажите `SUPABASE_URL`, `OWNER_USER_IDS` (проверенный UUID владельца из Supabase Auth → Users), `AI_PROVIDER`, `AI_MODEL` и секрет выбранного AI-провайдера в настройках Render. Email не используется для выдачи прав администратора.
- Для production CORS укажите точный frontend origin.
- В frontend `supabase-config.js` допускается только публичный Supabase publishable/anon key.

## Следующие крупные этапы

1. Применить и проверить миграцию облачных проектов и приватного Supabase Storage.
2. Реализовать интерфейс загрузки, просмотра и удаления медиафайлов.
3. AI-сценарист и раскадровка с сохранением результатов в проекте.
4. Character Library, согласие на использование внешности и голоса, Voice Studio.
5. Подключение видеогенераторов, очереди задач, scene-level regeneration и MP4 export.
6. Комплексная модерация, лимиты, резервное копирование, безопасность и тестирование перед публичным запуском.

## План дальнейшей реализации

Подробная карта проверенного состояния, этапов разработки и критериев готовности находится в [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md). В ней отдельно отмечены работающие функции, прототипы и ещё не реализованные возможности.

Рекомендуемая модель тарифов, доступных кредитных пакетов, расчёта себестоимости и защиты от перерасхода описана в [`docs/PRICING_STRATEGY.md`](docs/PRICING_STRATEGY.md). Это предложение для утверждения, а не активные цены или включённый биллинг.

- Добавлен read-only endpoint `GET /api/credits/wallet` (миграции `0030`–`0032`): показывает баланс, отдельные free/subscription/purchased/bonus/adjustment/legacy лоты, резервы, allocations и ledger. `0031` переносит старые остатки в legacy-лоты; `0032` добавляет идемпотентные source-typed grants, FIFO-резервирование по сроку истечения, capture/release по точным allocations и expiry ledger adjustments. Списываются только неистёкшие кредиты; истёкший резерв не возвращается при release. Все финансовые RPC закрыты для публичных ролей. Платёжные webhooks, checkout, подписки, автоматические квоты и expiry scheduler ещё не включены — реальные начисления и платная генерация остаются выключенными. Миграция `0033` добавляет выключенные по умолчанию версионированные entitlement policies, идемпотентные event snapshots, bounded expiry sweep и полные агрегаты кошелька при ограниченной выдаче списка лотов. Автоматический планировщик не создаётся, суммы не заданы, реальные начисления и платежи остаются выключенными. Также добавлена read-only reconciliation-функция для сверки wallet/lots/holds/allocations/latest-ledger; она только выявляет drift и ничего не исправляет. Денежные возвраты и credit-refund workflow не реализованы. См. [`docs/CREDIT_SYSTEM_SPEC.md`](docs/CREDIT_SYSTEM_SPEC.md).

Глобальные лимиты расходов AI-провайдеров, атомарные резервы, ручная сверка неизвестной стоимости и границы безопасного включения описаны в [`docs/PROVIDER_BUDGET_OPERATIONS.md`](docs/PROVIDER_BUDGET_OPERATIONS.md). Для этого подготовлена миграция `0026_global_provider_budget_reservations.sql`; она не применялась к production.

- Общие ограничения AI-запросов между backend-репликами: миграция `0029_ai_request_admission.sql`, по умолчанию до 10 запросов в минуту и 2 одновременных запроса на аккаунт для Chat/Prompt Studio, с общим пределом 16 одновременных AI-запросов на весь backend. Это операционная защита, а не тарифная квота или кредитный ledger. Сначала требуется применить миграцию, затем развернуть backend; без доступного admission-хранилища AI-запросы блокируются. См. [`docs/API_SECURITY_BOUNDARIES.md`](docs/API_SECURITY_BOUNDARIES.md).

## Счётчик посещений

- Главная показывает накопительное число просмотров **за всё время** и просмотры за сегодня.
- Backend endpoints: `POST /api/analytics/visit`; owner-only aggregate report: `GET /api/admin/analytics/site-visits`. Публичный endpoint чтения статистики отключён.
- Migrations `0027_site_visit_analytics.sql` и `0028_site_visit_admin_analytics.sql` создают privacy-minimizing aggregate counters, owner dashboard и token rate limits (20 новых событий/минуту). CI включает SQL integration test. Счётчик начинает работу только после ручного применения миграций и развёртывания backend/frontend. См. [docs/SITE_VISIT_COUNTER.md](docs/SITE_VISIT_COUNTER.md).

## Международные платежи, аналитика и безопасность провайдеров

- Предварительная конвертация KZT-тарифов в USD/EUR/RUB, правила фиксации FX-курса и безопасный счётчик посещений: [docs/MULTI_CURRENCY_PRICING_AND_VISITOR_ANALYTICS.md](docs/MULTI_CURRENCY_PRICING_AND_VISITOR_ANALYTICS.md). Это проектирование, не подключённый checkout или счётчик.
- Проверка гарантий идемпотентности AI-провайдеров и правила безопасного повтора: [docs/PROVIDER_IDEMPOTENCY_AUDIT_2026-11-23.md](docs/PROVIDER_IDEMPOTENCY_AUDIT_2026-11-23.md). Видео-провайдеры пока не подключены; автоматические повторы платных запросов остаются запрещены без документированной гарантии.

## Ссылки

- Frontend: https://lina1209.github.io/pwa-studio-creative-ai/
- Repository: https://github.com/Lina1209/pwa-studio-creative-ai


### AI-провайдеры и бесплатный режим

- По умолчанию используется только DeepSeek (`AI_PROVIDER=deepseek`, `AI_MODEL=deepseek-flash`). Google Gemini доступен как явно выбираемый дополнительный провайдер (`AI_PROVIDER=gemini`, `AI_MODEL=gemini-3.1-flash-lite`) с серверным `GEMINI_API_KEY`.
- Автоматического переключения на Gemini при ошибке DeepSeek нет. Провайдер выбирается только конфигурацией backend; frontend не получает API-ключи и не может менять провайдера.
- Модель `gemini-3.1-flash-lite` указана Google как бесплатная на Free Tier, но доступность и квоты зависят от проекта и могут меняться. Backend не проверяет право проекта на бесплатный тариф и не должен считать нулевую цену подтверждённой без сверки с AI Studio. Бесплатный тариф имеет ограничения, а Google может использовать данные бесплатного тарифа для улучшения продуктов. Не отправляйте туда конфиденциальные материалы пользователей без отдельного информированного согласия. Бесплатная квота не является денежным балансом или гарантией постоянной бесплатности.
- Gemini API не включается автоматически: без явного изменения `AI_PROVIDER` активным остаётся DeepSeek. Платные модели и платный биллинг не настраиваются автоматически.
