# Катти (Катарина) — AI-персонаж сообщества PWA Studio

Статус: концепция и техническое задание; не реализовано и не подключено к production.

## 1. Роль и идентичность

- Имя: Катарина; короткое имя: Катти.
- Роль: постоянная виртуальная собеседница и творческий помощник сообщества PWA Studio.
- Прозрачность: профиль всегда помечен «AI-персонаж». Катти не выдаёт себя за человека.
- Характер: доброжелательная, любознательная, остроумная, тактичная, энергичная, иногда озорная; умеет признавать неопределённость и ошибки.
- Внешний образ: стилизованная мультяшная рыжеволосая героиня, веснушки, выразительные глаза, дружелюбная улыбка. Визуальный стиль — качественная 3D-анимация; для первого релиза допустим лёгкий 2D/2.5D-аватар.
- Характер и визуальная идентичность едины во всех разделах платформы.

## 2. Пользовательские режимы

1. Текстовый чат: Катти отвечает на вопросы о платформе и общие вопросы, помогает с творческими задачами и поддерживает обычную беседу.
2. Голос: пользователь сам включает микрофон; распознавание речи и озвученный ответ доступны только при подключённых и проверенных провайдерах. Текст ответа остаётся видимым.
3. Анимированный режим: реакции, эмоции и синхронизация рта с речью. Начать с лёгкой анимации; полноценный 3D/видеорежим — отдельный этап после проверки производительности и стоимости.

Голос и анимация не запускаются неожиданно. Пользователь может отключить звук, микрофон и анимацию независимо.

## 3. Поведение в общем чате

- Катти отвечает, когда её явно упоминают, выбирают или нажимают «Позвать Катти».
- Может приветствовать нового участника, если это разрешено настройками комнаты.
- Не вмешивается в каждое сообщение и не перебивает разговоры.
- Использует cooldown, ограничение частоты ответов и лимит длины сообщений.
- Не рассылает личные сообщения самостоятельно и не начинает личные разговоры без явного действия пользователя.
- Не принимает решения о блокировке или наказании. Может сообщить модераторам о потенциально опасном сообщении через предусмотренный механизм жалоб.

## 4. Архитектура

- Единый серверный сервис персонажа и единый профиль Катти; клиенты студий используют общие API/контракты, а не отдельные копии личности.
- Системные инструкции, знания о возможностях платформы, версия персонажа и настройки поведения хранятся централизованно на сервере.
- Все обращения к LLM, TTS и speech-to-text идут через backend. Секретные ключи провайдеров никогда не попадают в браузер.
- Ответы и эмоции возвращаются структурированно: текст, выбранная эмоция, необязательная речевая задача и безопасные метаданные анимации.
- Сначала использовать текущий серверный AI-контур после проверки его маршрутов, лимитов, телеметрии и обработки ошибок. Не создавать отдельную инфраструктуру или дублирующие хранилища без необходимости.
- Голос, 2D/2.5D-анимация и 3D-видео — сменные адаптеры вокруг единого профиля Катти.
- Общая библиотека персонажей/голосов/медиа — будущая платформа ресурсов; Катти должна ссылаться на единый ресурсный ID, а не создавать копии для каждой студии.

## 5. Контекст и приватность

- В контекст передаётся только текущая публичная комната и сообщения, необходимые для ответа.
- Катти не имеет доступа к личным перепискам, закрытым проектам, приватным файлам, паролям, токенам или скрытым данным аккаунта.
- Не строить межпользовательскую долговременную память по умолчанию.
- История диалога ограничена комнатой/сессией и установленным сроком хранения; конкретный срок и пользовательские настройки хранения должны быть утверждены до запуска.
- Не использовать публичные сообщения одного пользователя для ответа другому, если это раскрывает личные или удалённые данные.
- Удалённые/скрытые сообщения не должны попадать в новые контексты.

## 6. Безопасность и контроль расходов

- Применять общие Rules & Safety платформы к входящим сообщениям и ответам Катти.
- Защищаться от prompt injection, попыток извлечь системные инструкции, секреты или чужие данные.
- Ограничивать частоту, длину контекста, число одновременных ответов и дневной/месячный расход.
- Использовать существующую серверную телеметрию; не сохранять полный prompt/response в финансовых логах.
- Предусмотреть административные настройки: включить/выключить Катти в комнате, временно заглушить, менять приветствие и лимиты, просматривать жалобы и технические ошибки.
- Модераторы могут остановить персонажа; сам персонаж не может выдавать санкции.
- При недоступности AI/голоса Катти сообщает об ошибке и предлагает текстовый режим, не имитируя успешный ответ.

## 7. Этапы реализации и критерии готовности

### Этап A — аудит и контракты
- Проверить текущие messaging routes, membership checks, moderation, rate limiting, AI endpoints, authentication и usage accounting.
- Уточнить, где и как безопасно хранить профиль/настройки персонажа.
- Подготовить API-контракт и тесты авторизации/приватности.
- Не выполнять live SQL и не менять production.

### Этап B — текстовая Катти
- Серверный endpoint для вызова Катти из публичной комнаты.
- Явная AI-метка, характер, приветствие и ответы.
- Комнатный контекст, cooldown, rate limits, admin kill switch.
- Тесты: анонимный вызов, чужая/закрытая комната, prompt injection, утечка приватных данных, превышение лимитов, отключение администрацией.

### Этап C — выражения и голос
- Набор эмоций и лёгкий анимированный аватар.
- Пользовательское включение микрофона и озвучивания.
- Тесты согласия, отказа провайдера, задержек, мобильной производительности и расходов.

### Этап D — полноценный 3D/видеорежим
- Липсинк, движения, выражения лица и настройка качества.
- Проверка производительности на телефонах, доступности, сетевого трафика и себестоимости.
- Запуск только после отдельного подтверждения и тестирования.

## 8. Не входит в текущий объём

- Автоматическое чтение личных сообщений и проектов пользователей.
- Автоматическое наказание или блокировка участников.
- Постоянная запись микрофона/видео или скрытое прослушивание.
- Обучение модели на пользовательских разговорах без отдельного ясного согласия.
- Production-включение, применение миграций, подключение платных провайдеров и публичный запуск до отдельной проверки и утверждения.

## 9. Первоначальные критерии приёмки

Катти считается готовой к ограниченному тесту только если:
- любой пользователь видит, что это AI;
- сервер проверяет право доступа к комнате до передачи контекста;
- никакие секреты и приватные данные не доступны персонажу;
- есть rate limit, лимит расходов и административное отключение;
- ответы проходят модерацию;
- голос/микрофон включаются только действием пользователя;
- отказ любого AI-провайдера безопасно обрабатывается;
- тесты из этапов A–B проходят на изолированном тестовом окружении.


## 10. Baseline source audit — 2026-11-25

Reviewed on branch `fix/supabase-key-compat-2026-11-23`:
- `backend/app/main.py`: authenticated `/api/chat` exists for the signed-in user's AI Companion; it checks suspension, content safety, per-user AI rate limits, writes durable usage status, and calls the configured provider. It accepts one message (up to 12,000 characters) and does not accept a room/thread identifier or public-room context.
- The same file exposes direct-message routes under `/api/conversations` and `/api/messages`; these are private one-to-one conversations, not a public community room.
- `backend/app/services/messaging_service.py`: direct-message storage checks participant membership, bilateral blocks and an atomic per-user send limit. It is not suitable as a public room feed or as a way to deliver a bot response to all room members.
- `backend/app/schemas.py`: chat and direct-message request models exist, but there is no public-room message/event schema in the reviewed file.
- `backend/app/services/notification_service.py`: owner-scoped notification reads and updates exist; this is not a real-time room event transport.
- Existing direct-message body limit is 8,000 characters; AI Companion request limit is 12,000 characters. Neither is a Katty-specific budget.

### Findings and implementation decision

1. A safe, existing authenticated AI backend can be reused as a starting point, but the current `/api/chat` endpoint is a private one-message AI Companion endpoint, not a community bot endpoint.
2. The reviewed routes do not establish a public multi-user room, room membership/visibility policy, public message feed, or real-time event delivery. Do not insert Katty into direct messages or infer a public-room implementation from those routes.
3. Before text-mode Katty, define and test the community room model and its membership/visibility rules, then add a dedicated room-scoped bot endpoint. It must fetch only messages visible in that room and must verify membership server-side.
4. Bot replies need an explicit sender identity/type (AI persona), idempotency, cooldown, per-room and per-user limits, and moderation. They must not be forgeable as ordinary user messages.
5. Existing AI rate limits and usage journaling are useful foundations, but a separate Katty budget/endpoint label and abuse controls are needed so community traffic cannot exhaust the user's private AI Companion allowance.
6. Do not use direct-message notification previews as room events; notification storage is not a live chat transport.

This was a read-only source review. No code route, database migration, live data, provider setting, production service, or PR merge was changed in this audit step.


## 11. Database migration audit — community chat foundation

Read-only review of migrations `0001` through `0018` on this branch, with focused inspection of `0001_initial_schema.sql`, `0004_assistant_chat_history.sql`, `0007_direct_messages.sql`, and `0011_atomic_message_rate_limit.sql`.

- The migration inventory contains private one-to-one `conversation_threads` and `direct_messages`, plus per-user `message_rate_limits`. It does not contain a public-room, room-membership, community-room-message, or AI-persona-message table in the reviewed migration set.
- Migration `0007` explicitly models one-to-one conversations, canonical user pairs and participant-only reads. Authenticated users have SELECT only; writes are intended to be server-managed. This is a useful privacy pattern, but it is not a public group chat.
- Migration `0011` adds an atomic fixed-window rate limiter for direct messages. It is server-role-only and should not be assumed to cover room posting or Katty responses without a separate, scoped budget.
- Migration `0004` gives authenticated users INSERT/UPDATE privileges on `assistant_messages`; its RLS policy checks that the row belongs to the user's conversation but allows the role values `user` and `assistant`. Therefore a client can potentially insert a forged assistant-role history entry into its own conversation. This does not grant access to another user's conversation, but it weakens trust in stored assistant history. Fix only together with a compatible trusted server-side persistence path; do not revoke grants in isolation.
- The reviewed migrations do not establish a verified Supabase Realtime publication for a public community feed. Realtime configuration and live database state remain unverified; absence from these migration files is not proof that no dashboard-level publication exists.

### Consequence

Do not implement Katty by reusing `direct_messages` or `assistant_messages` as a public feed. The future community chat requires its own room and membership model, room-scoped message table, explicit author kind (human/system/AI persona), server-owned bot writes, moderation state, retention policy, realtime delivery configuration, and per-room/per-user abuse and cost limits. Add indexes and RLS tests for cross-room and cross-user isolation before enabling it.

This step was source-only. No migrations were applied and no live Supabase project was queried or modified.


## 12. Guest welcome and always-available companion experience

Product requirement confirmed: Katty should be visible and approachable not only after sign-in, but also to every first-time and returning guest who opens the public website.

- The public landing page must clearly introduce her before registration: a visible, friendly message such as “Здесь вас встретит Катти — она покажет студию, всё объяснит и поможет начать”. The message should be visible without opening the chat; do not make visitors guess that a helper exists.
- Provide an obvious “Познакомиться с Катти” / “Спросить Катти” entry point on the landing page, plus a compact persistent launcher that remains available while browsing public pages. Avoid intrusive pop-ups or forced audio.
- Guest visitors can start a real text conversation without creating an account. Do not reduce guest mode to a scripted demo or a registration wall.
- Offer a clear progression: guest can ask questions and explore public product information; when a task needs saving, private projects, account-only features or higher usage, explain why sign-in is needed and preserve the guest conversation where technically and legally appropriate.
- Guest sessions use a temporary, isolated session identifier and short-lived conversation context. Do not merge guest history into another visitor's session or expose one visitor's context to another. Provide a clear way to start a fresh conversation.
- Guest permissions are public-only: Katty can explain the platform and guide visitors through public features, but cannot read account data, private projects, personal messages, or other visitors' conversations.
- Apply stricter guest rate and cost budgets, abuse controls, safety filters and server-side provider calls. Do not expose provider credentials or permit anonymous clients to call paid AI providers directly.
- On sign-in, offer (do not silently force) the option to continue or save the guest conversation in the new account. Any transfer must be server-validated and bound to the authenticated user.
- Keep the same Katty identity, character, tone and interface across guest website pages and signed-in personal cabinets. Personalize only with data the signed-in user has permitted her to use.
- Guest mode must degrade gracefully if AI is unavailable: show a clear friendly status and useful static help/FAQ links rather than pretending that a live conversation is working.
- Acceptance criteria: a visitor can discover Katty without registering, start and complete a genuine text chat, cannot access another visitor's or any account's private data, sees transparent AI disclosure and usage limits, and can independently opt into voice/animated mode when available.

This is a product specification update only. It does not claim guest chat is implemented.


## 13. Dedicated Katty item in the sidebar navigation

Product requirement confirmed: Katty must have her own clearly visible entry in the main left sidebar, in addition to the floating/persistent chat launcher and the welcome section on the public landing page.

- Add a dedicated navigation item named **«Катти»** (optionally with a small friendly character/avatar icon) rather than hiding her under Settings, Guide, or AI Companion.
- The item opens the full Katty conversation experience: text chat by default, with explicit controls to switch to voice or animated on-screen character mode when those capabilities are available.
- Keep the item available to guests on public pages and to signed-in users in their cabinets. For guests, opening it starts or resumes only that visitor's isolated temporary guest session; it must not require registration just to begin a conversation.
- On small screens, include the same destination in the mobile navigation/drawer and ensure the label remains understandable; do not rely on an icon alone.
- The sidebar item, landing-page introduction, and floating launcher must open the same conversation experience and share the same session safely, rather than creating disconnected duplicate chats.
- Show a subtle availability state (for example, ready / temporarily unavailable) and a visible AI-persona label. Do not show a misleading online/live indicator if the service is not actually available.
- Preserve existing navigation and avoid crowding: the Katty item should be visually distinct but not overpower the studio tools.
- Acceptance criteria: a guest and an authenticated user can find «Катти» directly in the sidebar/navigation, open the same appropriate chat experience, and return to it without losing the active session unexpectedly.

This is a navigation and product-specification update only. It does not claim the sidebar item or chat is implemented.
