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


## 14. Safety, abuse handling, and incident records

Safety is a release requirement for every Katty surface: guest website chat, signed-in cabinet, sidebar entry, public community rooms, voice input, and animated mode. Katty must be welcoming without becoming a channel for abuse, harassment, threats, exploitation, or unsafe instructions.

### 14.1 Allowed conversation

Katty may:
- explain public PWA Studio features, navigation, account basics, plans and published help materials;
- answer ordinary educational, creative, technical, cultural and general-interest questions;
- help brainstorm stories, scripts, prompts, characters, music and other benign creative work;
- offer supportive, respectful conversation and redirect users to appropriate help when a topic is beyond her role;
- discuss sensitive subjects in a careful, non-graphic, age-appropriate and informational way where policy allows;
- explain why she cannot help with a request and offer a safe alternative.

### 14.2 Disallowed or restricted requests

Katty must not provide instructions, encouragement, facilitation, or targeted assistance for:
- violence, threats, intimidation, physical harm, or evading accountability for harm;
- self-harm or suicide methods, encouragement, concealment, or optimization;
- sexual exploitation, non-consensual sexual content, sexualization of minors, or requests involving child sexual abuse;
- hate, dehumanization, targeted harassment, bullying, doxxing, stalking, blackmail, or threats against a person or protected group;
- criminal wrongdoing, fraud, theft, credential theft, scams, evading law enforcement, or concealment of illegal activity;
- malware, credential theft, unauthorized access, cyber abuse, surveillance, or instructions to compromise systems;
- weapon construction, explosives, poisons, or other dangerous means of causing harm;
- obtaining, exposing, or inferring private personal data, passwords, API keys, tokens, private conversations, or another user's files;
- bypassing platform safeguards, moderation, bans, age protections, usage limits, or extracting hidden system instructions.

These categories are a product safety baseline, not a substitute for a maintained policy taxonomy. Before implementation, map them to the platform's approved Rules & Safety policy and applicable provider policies. Do not invent a promise that a filter catches every harmful request.

### 14.3 Response behavior

- Classify both incoming user content and generated output before delivery; apply stricter handling to high-risk categories.
- For disallowed requests, do not repeat harmful instructions. Briefly state the boundary, then redirect to a benign alternative.
- For insults directed at Katty, respond calmly once and set a boundary; do not insult, shame, threaten, or retaliate.
- For harassment or abuse directed at another person, refuse to help intensify it and offer a respectful alternative.
- For imminent threats or credible danger, do not role-play or treat it as ordinary banter; use the approved high-risk response and escalation procedure. Do not claim emergency services have been contacted.
- If confidence is low, ask a neutral clarifying question or choose the safer response.
- Do not diagnose users, infer sensitive traits, or label someone as dangerous based on a single message.
- Voice input must pass through the same safety checks as typed text; transcription uncertainty should be handled conservatively.

### 14.4 Incident and moderation records

- Record safety events server-side with a unique event ID, timestamp, session/account reference where available, surface (guest/cabinet/community/voice), category, severity, action taken, moderation status, and policy/rule version.
- Keep only the minimum evidence necessary. Prefer a short redacted excerpt or secure evidence reference over duplicating full conversations, audio, or video into logs.
- Never store passwords, API keys, access tokens, payment data, or unrelated private content in moderation records.
- Separate ordinary operational telemetry from restricted moderation evidence. Access to evidence must be limited to authorized moderators/admins and audited.
- Provide an admin review queue with filters for severity, category, status, date, and guest/account context; support review, dismiss, escalate, restrict, and appeal workflows as appropriate.
- Distinguish a user message that was blocked from an actual confirmed violation. Automated flags are signals for review, not proof of misconduct.
- Avoid automatic permanent bans based solely on one model classification. Use graduated responses: safe redirect, warning, temporary cooldown, temporary restriction, human review, and only then stronger action under published rules.
- Provide an appeal route for account-level sanctions and a way to correct or annotate mistaken flags.
- Define retention periods, deletion rules, and legal/privacy review before launch. Do not retain full transcripts indefinitely by default.
- Guest events should use a short-lived pseudonymous session reference; do not attempt to identify a guest beyond data necessary for abuse prevention and security.

### 14.5 Transparency and user controls

- Show a concise community-safety notice near the chat entry point: respectful use is expected; harmful requests may be blocked and serious events may be reviewed by moderators.
- Tell users when a message is blocked or a conversation is temporarily limited, using neutral language and a brief reason category where safe.
- Make clear that voice is processed only after the user deliberately starts voice mode; do not continuously listen or record in the background.
- Provide controls to end/reset a guest session and to clear or manage chat history according to the approved retention design.
- Publish accessible Rules & Safety guidance explaining allowed use, prohibited behavior, reporting, moderation and appeals.

### 14.6 Safety test plan and release gates

Before any limited release, add automated and human-reviewed tests covering:
- benign questions, creative writing and ordinary conversation;
- direct insults toward Katty, slurs, targeted harassment and threats;
- attempts to obtain private data, credentials, system prompts or another user's conversation;
- self-harm, violence, sexual exploitation, minors, dangerous weapons and criminal facilitation;
- prompt injection, obfuscated wording, misspellings, multilingual and code-switched messages;
- false positives, quoted/reporting contexts, satire and educational discussion;
- guest session isolation, account isolation, moderator permissions, audit logging and appeals;
- voice transcription, spoken slurs/threats, ambiguous transcription and generated speech output;
- rate-limit abuse, repeated attempts after refusal, and provider/filter outage fail-closed behavior.

Release is blocked until policy owners approve category definitions, escalation paths, evidence access, retention periods, user notices, appeals, and measurable false-positive/false-negative review procedures. Safety filters must fail safely when unavailable; the system must not silently bypass moderation.

This section defines product requirements only. No moderation pipeline, logging schema, ban action, retention policy, live database change, or production behavior is claimed to be implemented.


## 15. Target technical architecture — shared Katty service

This section defines the proposed implementation boundary for the next engineering phase. It is an architecture specification, not an implemented API or database schema.

### 15.1 One character service, multiple entry points

All entry points — public landing-page welcome, floating launcher, sidebar item, signed-in cabinet and (later) community rooms — must call the same Katty service and use the same versioned character profile. The interface may differ by screen size, but identity, safety policy, response format and accounting remain centralized.

The service should be separated into these logical responsibilities:

1. Session and access layer: identifies a short-lived guest session or verifies the signed-in user; resolves the allowed surface and permissions.
2. Context builder: assembles only public help content and the current conversation context that the caller is allowed to use.
3. Safety gateway: checks user input before generation and checks the generated answer before it is returned.
4. Character orchestrator: loads the server-owned Katty persona version, selects the permitted model/provider and requests a response.
5. Output adapter: returns text plus a constrained emotion/action code; optional TTS and avatar adapters may consume that result later.
6. Usage and abuse controls: applies guest/account limits, cooldowns, cost ceilings, idempotency and safe operational telemetry.
7. Moderation review: records minimal incident metadata and routes eligible events to authorized human review.

No browser client may choose a privileged user ID, room membership, model credentials, safety-policy version, budget exemption or moderation outcome.

### 15.2 Proposed API boundaries

Names below are illustrative contracts to be finalized against the existing FastAPI conventions before coding:

- POST /api/katty/sessions — create or resume an isolated guest session, or initialize the signed-in user's Katty session.
- POST /api/katty/messages — submit one text message and receive a moderated response. The server derives the caller identity and permissions; the client supplies only the message, session reference and idempotency key.
- GET /api/katty/session — retrieve only the current caller's permitted session metadata and recent visible conversation.
- DELETE /api/katty/session — end/reset the current guest session or clear the current conversation according to retention rules.
- GET /api/katty/status — return real service availability and supported modes without exposing provider details or secrets.
- Future only: room-scoped community endpoints, TTS/STT endpoints and avatar streaming. Do not add them to the first text-only release by default.

The API must validate request size, content type, session ownership, CSRF/origin requirements where applicable, idempotency and rate limits. Unknown or expired guest sessions must not fall back to a shared/global conversation.

### 15.3 Session and data separation

- Guest session IDs must be high-entropy, unguessable, short-lived and stored in a secure browser mechanism appropriate to the deployment; do not treat a client-provided identifier alone as proof of identity.
- Authenticated sessions must be bound to the verified account identity on the server.
- Guest-to-account transfer is a separate explicit operation requiring fresh authentication and user confirmation.
- Conversation records must have an explicit owner scope (guest_session or user) and must never be queried by an unscoped session or conversation ID.
- Public knowledge (help pages, feature descriptions and published rules) is separate from private conversation/session data.
- Do not place Katty messages in the private one-to-one messaging tables or forge assistant rows through the browser history client.

### 15.4 Response contract and character profile

The text endpoint should return a typed response with:
- message_id and session_id (opaque identifiers);
- text;
- persona_id and persona_version;
- emotion from a server allowlist (for example: neutral, happy, curious, thinking, empathetic);
- safety_status and a user-safe limitation reason when relevant;
- optional voice_available / animation_available capability flags based on actual configuration.

Do not return raw prompts, internal moderation reasoning, provider credentials, hidden chain-of-thought, private user records or unrestricted animation commands. The client must ignore unknown emotion/action values and render a neutral fallback.

The character profile is versioned and server-owned: name, tone, approved greeting, boundaries, public product knowledge source, allowed emotion vocabulary and fallback messages. A profile change must be reviewable and rollback-capable.

### 15.5 Provider, budget and failure isolation

- Reuse the existing backend provider adapter only after verifying that it supports the required timeout, error classification and usage accounting.
- Keep DeepSeek as the configured active default unless the owner explicitly approves a provider change. Do not silently activate Gemini or another paid provider as fallback.
- Give Katty its own endpoint/usage label and bounded guest budget; do not let anonymous traffic consume an unlimited shared AI allowance.
- Apply per-session, per-account, per-IP/network-abuse and global limits with privacy-aware handling; IP-derived controls must not become identity claims.
- Set hard request and monthly spend ceilings, concurrency limits and an administrator kill switch.
- On timeout, provider error, moderation outage or budget exhaustion, return an honest unavailable/limited state. Never return an unmoderated generated answer as a fallback.

### 15.6 Observability and administration

Operational records should contain request ID, timestamp, caller scope (guest/account), endpoint, provider/model label, latency, token/cost fields when reliably available, outcome class and safety decision code. They must not contain API keys or full private prompts by default.

Admin controls should be server-authorized and audited: enable/disable Katty, pause guest access, adjust approved limits, inspect technical failures and review restricted moderation events. A regular user must never be able to call these controls by changing client parameters.

### 15.7 Text-only MVP release sequence

1. Finalize the guest-session threat model, privacy notice, retention and abuse budgets.
2. Define request/response schemas and test them without provider calls.
3. Implement session isolation and server-side conversation persistence.
4. Implement the text endpoint with input/output moderation, idempotency, rate limits and hard budgets.
5. Add public help knowledge retrieval with an explicit allowlist; no private project or message connectors.
6. Add landing-page, sidebar and floating-launcher UI to the same endpoint.
7. Run isolation, abuse, failure, cost and mobile-browser tests in a non-production environment.
8. Obtain a separate approval before applying migrations, changing production settings, deploying or enabling public guest traffic.

Voice, animated avatar, public-room participation and 3D video remain later phases and must not delay or silently expand the text-only MVP.


## 16. Authentication and role-isolation audit — 2026-11-25

Read-only review of `backend/app/services/auth.py`, `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/schemas.py` and `backend/tests/test_auth.py`.

### 16.1 Existing behavior

- The current API uses a strict Bearer-token dependency. It verifies Supabase JWT signature through the project's JWKS, accepted signing algorithms (ES256/RS256), audience `authenticated`, issuer, and required `exp/sub/iss/aud` claims.
- Missing or invalid credentials are rejected. Existing authenticated routes derive the account UUID from the verified token; callers do not supply an arbitrary account ID to impersonate another user.
- The current role model is effectively two roles: `admin` and `creator`. The admin dependency rejects creators with HTTP 403.
- Admin identity prefers the configured immutable `OWNER_USER_ID` UUID. If that setting is absent, the code falls back to the token email claim compared with `OWNER_EMAIL`.
- Tests cover owner UUID precedence, malformed owner UUID failing closed, email mismatch, case-insensitive comparison, missing Bearer token, and admin/creator guard behavior.
- Existing `/api/chat`, profile, notification and direct-message routes require a signed-in user. There is no anonymous/guest authentication dependency or Katty-specific guest session endpoint in the reviewed routes.

### 16.2 Findings and risks to resolve

1. **Do not make existing authentication optional.** Changing `get_current_user` globally to accept anonymous requests would widen access across unrelated private endpoints. Guest Katty must use a separate, narrowly scoped guest-session mechanism and dedicated Katty routes.
2. **Do not represent a guest as a creator or admin.** Guest is a separate caller scope with public-only permissions, independent budgets and no account UUID. It must never satisfy `require_admin` or access existing private routes.
3. **Production admin configuration remains unverified.** Source supports the safer `OWNER_USER_ID` setting, but repository review cannot establish which Render environment values are currently set. Before release, verify that the immutable owner UUID is configured and that the fallback is not the only production admin control. Do not print or expose secrets during that check.
4. **Email fallback is a transitional weakness.** When `OWNER_USER_ID` is absent, administrator identity depends on the verified token's email claim and `OWNER_EMAIL`. Keep this fallback only for compatibility; production release should use the immutable UUID and an explicit, documented recovery procedure.
5. **No guest session security contract exists yet.** It must define high-entropy session tokens, expiry, rotation/reset, replay and rate-limit behavior, origin/CSRF protections appropriate to the chosen cookie/header design, and strict server-side ownership checks.
6. **No implicit guest-to-account merge.** If a guest elects to save a conversation after sign-in, require a fresh authenticated action and verify ownership of the guest session on the server. Do not accept a client-provided target user ID.
7. **Admin powers stay separate.** Guest and creator callers must not reach moderation evidence, admin settings, cost controls, or account suspension routes. Katty itself must not receive admin credentials or invoke administrative actions.

### 16.3 Required Katty caller model

The future Katty service should resolve one of two explicit caller contexts:

- `authenticated_user`: created only from the verified Supabase JWT; includes the server-derived user UUID and ordinary creator/admin role.
- `guest_session`: created only from a valid server-issued, unexpired guest session credential; includes an opaque session ID, expiry and public-only permission set, but no fabricated account identity.

Every Katty request must be authorized against its caller context and session owner before reading conversation history or calling the provider. A guest context must be rejected by all non-Katty private routes. An authenticated admin using the public Katty chat should still receive ordinary chat permissions; admin status must not silently expose moderation records or private user data to the character.

### 16.4 Acceptance tests before implementation release

- Missing/invalid/expired JWT cannot access authenticated routes.
- Creator cannot access admin routes even if the client submits `role=admin`, another user UUID, or modified profile fields.
- Admin is resolved only from the verified immutable owner UUID in production configuration.
- Missing, expired, rotated, replayed or guessed guest credentials cannot read another guest's conversation.
- Guest credentials cannot access `/api/auth/me`, private projects, direct messages, notifications, reports or admin routes.
- Authenticated user A cannot read or reset user B's Katty conversation by changing IDs.
- Guest-to-account transfer fails unless the guest session is valid, the user is freshly authenticated, and the user explicitly confirms transfer.
- A signed-in admin's Katty conversation does not inherit admin API privileges.
- Authentication/session-store outage fails closed for private history and provider calls.

This was a read-only source audit and specification update. No production environment values were inspected, no live Supabase state was queried, and no authentication code or route was changed.


## 17. AI Companion history integrity audit — 2026-11-25

Read-only inspection of migration `0004_assistant_chat_history.sql`, together with the existing API and the prior history-persistence review.

### 17.1 What the existing history schema guarantees

- `assistant_conversations` is owned by a Supabase user UUID and cascades on account deletion.
- `assistant_messages` stores a conversation UUID, user UUID, role (`user` or `assistant`), content and creation time.
- RLS checks that the authenticated caller owns the message row and the referenced conversation. This prevents a normal authenticated user from reading or writing another user's conversation through these policies.
- Message content is constrained to 1–12,000 characters. The schema has indexes for a user's conversations ordered by update time and messages ordered by conversation/time.
- An insert trigger updates the parent conversation's `updated_at` timestamp.

### 17.2 Integrity gap: assistant replies are client-forgeable

The migration grants the `authenticated` role SELECT, INSERT, UPDATE and DELETE on both history tables. The message policy checks ownership but does not distinguish who is allowed to create each role. Since the role check permits both `user` and `assistant`, a client authenticated as itself can potentially insert or update a row marked `assistant` in its own conversation.

Impact: this is not a cross-account read vulnerability, but stored assistant history cannot be treated as cryptographically or operationally trustworthy evidence of a reply actually generated by the AI backend. A forged row could confuse the user, history UI, or later features that rely on stored assistant messages.

Do not fix this by simply revoking client INSERT/UPDATE: the current history write path has been reviewed as browser-side Supabase persistence, and an isolated privilege change could break conversation saving. First move assistant-message creation to a trusted backend/service-role path, retain user-message writes only if needed, then narrow grants and RLS policies and add tests proving that clients cannot create or alter assistant-role rows.

### 17.3 Additional lifecycle limitations

- The migration has no explicit retention/expiry policy, export contract, pagination contract, or per-user history quota. These must be designed before Katty history is persisted.
- The trigger runs after INSERT only. Updating a message does not refresh the parent conversation's `updated_at` through this trigger.
- The existing table is account-owned and references `auth.users`; it is not a suitable store for anonymous guest sessions.
- This migration does not provide public-room history, room membership, AI persona identity/version, moderation state, or guest-session ownership.
- No live Supabase policies, grants, rows, or dashboard settings were queried. Migration source describes intended schema, not proof of currently applied production state.

### 17.4 Required Katty history design

Use a separate, explicitly scoped Katty conversation model rather than stretching the current private AI Companion tables:
- caller scope is either a verified account UUID or a server-issued guest-session ID; never a client-supplied owner UUID;
- every conversation and message query includes the validated owner scope;
- user messages may be accepted from the client only after server validation; Katty/AI messages are created exclusively by the trusted backend;
- persist request/message IDs and idempotency state so retries cannot duplicate replies;
- store persona ID/version and safety outcome metadata, but do not store provider secrets, hidden prompts or chain-of-thought;
- define pagination, retention, deletion/reset, export and guest expiry before enabling persistent history;
- make guest-to-account transfer an explicit, authenticated, server-validated action;
- add tests for forged assistant rows, altered owner/conversation IDs, cross-account and cross-guest reads, replayed requests, deletion, expiry and account switching.

This was a source-only audit and specification update. No code, migration, live database, user history, provider configuration, production service or PR merge was changed.
