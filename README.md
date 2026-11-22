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
- LiteLLM adapter for configured OpenAI, DeepSeek, Anthropic or Ollama provider.
- Initial text safety checks. This is not full multimodal moderation.

## Важные ограничения

- Синхронизация проектов зависит от применения `supabase/migrations/0005_cloud_projects_and_storage.sql`; до проверки миграции и теста на втором устройстве не считайте облачную синхронизацию подтверждённой.
- AI-сценарист внутри этапов Миникиностудии, генерация изображений/видео, клонирование голоса, timeline editor and MP4 rendering are not connected yet. The stage editor currently saves and edits production notes/text locally.
- История версий хранится вместе с локальным проектом в браузере; очистка данных браузера может удалить её.
- AI endpoints require a deployed backend, valid Supabase URL, provider credentials and a signed-in session.
- A service worker provides offline shell fallback. Core HTML/JS/CSS assets use network-first updates with cached fallback.
- Supabase migration files are source-of-truth drafts; do not rerun old migrations blindly against an already configured live project.

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
- Укажите `SUPABASE_URL`, `OWNER_EMAIL`, `AI_PROVIDER`, `AI_MODEL` и секрет выбранного AI-провайдера в настройках Render.
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

- Добавлен read-only endpoint `GET /api/credits/wallet`: показывает собственный доступный/зарезервированный баланс, активные резервы и последние записи ledger. Отсутствующий кошелёк отображается как 0; автоматических начислений и платежей endpoint не выполняет. Раздельные лоты, истечение, подписки, возвраты и billing webhooks остаются следующими этапами. См. [`docs/CREDIT_SYSTEM_SPEC.md`](docs/CREDIT_SYSTEM_SPEC.md).

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
