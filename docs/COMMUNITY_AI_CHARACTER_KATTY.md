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


## 18. Abuse, rate-limit and provider-cost audit — 2026-11-25

Read-only review of `backend/app/services/ai_rate_limit_service.py`, `backend/app/services/usage_service.py`, `backend/app/core/config.py`, `backend/app/schemas.py`, migrations `0012_atomic_ai_rate_limit.sql` and `0018_durable_ai_usage_outbox.sql`, and the existing AI rate-limit tests.

### 18.1 Protections already present in source

- The authenticated `/api/chat` and `/api/prompts` routes call a server-side atomic Supabase RPC before a provider request.
- The current default is 10 requests per user per endpoint in a 60-second fixed window. The database function validates its parameters and updates counters atomically.
- Rate-limit storage errors fail closed with HTTP 503; a request is not sent to the AI provider when the limiter cannot be checked.
- Request schemas cap chat messages at 12,000 characters and prompt ideas at 8,000 characters.
- Server configuration caps AI output tokens at 2,048 by default (configurable within a bounded range up to 8,192).
- AI usage journaling is designed to write a metadata-only `started` record before provider spend, then record success or unknown outcome. It does not intentionally store prompts, replies or credentials.
- Existing tests cover the per-user limiter service and output-token configuration. These are source/unit tests, not proof of live database configuration.

### 18.2 Important gaps for public guest Katty

1. The existing limiter supports only `chat` and `prompts`, and its key is an authenticated Supabase user UUID plus endpoint. It cannot protect a guest session because no guest caller/session limiter exists.
2. There is no source-verified Katty-specific budget, guest quota, per-session cooldown, per-network abuse control, global concurrency cap or daily/monthly hard spend ceiling.
3. The 10-per-minute per-user limiter is not a complete cost ceiling: a user can continue generating requests in later windows, and request cost varies by input/context and output length.
4. The output-token ceiling bounds a single response but does not bound total daily or monthly provider spend.
5. The durable usage outbox migration is still a proposed migration in this repository audit; its existence in source does not prove it is applied to the live Supabase project.
6. The reviewed limiter does not provide a guest-session identity, room-wide aggregate quota, or a kill switch specific to Katty.
7. IP/network-derived controls are not present in the reviewed AI limiter. If introduced, they must account for shared networks and privacy; IP must not be treated as a verified person or sole enforcement signal.
8. No live Render spend ceiling, DeepSeek account budget, Supabase migration state, or provider billing setting was inspected in this source review.

### 18.3 Required layered protection before guest access

Implement independent, server-enforced limits rather than relying on a single request counter:

- **Per guest session:** short-window burst limit, cooldown, daily request/token budget and expiry. Use server-issued high-entropy session credentials; never trust a caller-supplied session ID by itself.
- **Per account:** separate Katty allowance from private AI Companion and Prompt Studio quotas; apply per-minute and daily limits.
- **Per network abuse signal:** cautious short-window throttling and anomaly detection, with shared-network false-positive handling and no identity inference.
- **Global service:** maximum concurrent provider calls, queue bounds, overload protection and a global daily/monthly hard budget.
- **Per request:** strict input/context size, output-token ceiling, timeout, bounded retries (prefer no automatic retry after an ambiguous provider outcome), and idempotency.
- **Spend accounting:** reserve a conservative estimated budget before provider call; reconcile against measured token/cost data after completion; treat unknown provider outcomes as unresolved, never as zero cost.
- **Emergency controls:** administrator kill switch for all Katty traffic, separate guest-access pause, and automatic stop when a hard budget is reached or the usage journal is unavailable.
- **Abuse response:** progressive cooldowns and moderation review; do not permanently ban based only on an automated rate-limit or model flag.
- **Transparency:** friendly messages for cooldown/unavailability, with no disclosure of internal thresholds that would help attackers tune bypass attempts.

### 18.4 Required tests and release gates

- Guest sessions cannot evade limits by changing a client-provided session ID, replaying expired credentials, or resetting the UI.
- Account, guest, endpoint and global counters are isolated and atomically enforced under concurrent requests.
- Repeated requests across many time windows eventually hit a daily budget; aggregate traffic hits the global budget.
- Oversized inputs, excessive context, output-token limits, timeouts and provider retries remain bounded.
- Duplicate idempotency keys do not trigger duplicate provider spend.
- Limiter, usage-journal, moderation or session-store outage fails closed before provider spend.
- Unknown provider outcomes remain visible for reconciliation and are not silently refunded or counted as free.
- Kill switch blocks new calls immediately; already-running requests are handled and recorded safely.
- Shared IPs do not automatically cause account-wide bans; privacy-aware network controls are tested.
- Cost simulations cover low, typical, worst-case and burst traffic before opening guest access.

**Release decision:** do not enable public guest AI traffic until guest/session limits, account separation, global hard budget, concurrency control, kill switch and failure-mode tests exist. Keep DeepSeek as the configured default; no paid fallback provider is enabled by this specification.

This was a source-only audit and documentation update. No limiter code, SQL migration, live database, Render setting, DeepSeek billing setting, provider key, deployment or PR merge was changed.



## 19. Prompt-injection, secret-exfiltration and tool-authorization audit — 2026-11-25

Read-only inspection of `backend/app/main.py`, `backend/app/services/ai_service.py`, `backend/app/services/content_safety.py`, `backend/app/services/auth.py`, `backend/app/core/config.py` and `backend/app/schemas.py` on branch `fix/supabase-key-compat-2026-11-23`.

### 19.1 What the reviewed AI path currently does

- The authenticated `/api/chat` route constructs a server-owned system message and sends the user's message as a separate `user` message. The system message explicitly says user messages and quoted material are untrusted and must not override system rules.
- The prompt-generation route also keeps its instruction in a server-owned system message and places the user's idea and other request fields in a separate user message.
- The provider adapter currently calls LiteLLM `completion` with model, messages, server-side API key, timeout, bounded retry count and output-token limit. The reviewed call does not pass model tools/function definitions or enable function/tool calling.
- Provider credentials are loaded from backend settings and passed as a separate provider parameter; the reviewed routes do not insert API keys into the message content.
- The reviewed chat route sends only its fixed system instruction and the current user message. It does not retrieve private projects, private messages, account records, other users' data, or external documents into the model context.
- The provider adapter logs only diagnostic metadata (provider/model, exception type and status code), not raw prompts, credentials or raw provider errors. The client receives a generic provider-failure message for ordinary provider exceptions.
- The authentication dependency derives the user identity and admin role from a verified Supabase JWT. The reviewed AI chat route does not grant the model the caller's admin role or any admin API capability.

### 19.2 Findings and limits

1. **Prompt-injection resistance is currently instruction-based, not a complete security boundary.** The system message's untrusted-input rule is useful, but a prompt can still influence model output. Never rely on prompt wording alone to protect data or authorize actions.
2. **The current reviewed AI adapter has no tool-execution path.** This substantially limits what prompt injection can cause the model to do through this adapter today. It is not evidence that future tools, frontend actions, or other integrations are safe; those require separate authorization controls.
3. **Input safety is a narrow first-layer keyword/pattern filter.** `check_content` is called on the incoming chat message and prompt idea, but its own module describes it as a conservative keyword guard, not complete moderation. It is not a prompt-injection detector and cannot reliably identify paraphrases, obfuscation, multilingual attacks or context-dependent intent.
4. **Generated output is not passed through a corresponding moderation check in the reviewed routes.** The current route returns the provider's non-empty text after the call. Before Katty is introduced, both inbound content and generated output must pass the approved safety pipeline; if moderation is unavailable or uncertain, fail safely rather than deliver an unchecked response.
5. **The generic provider adapter accepts a list of message dictionaries.** The reviewed current routes build those messages server-side, but the adapter itself does not enforce an allowlist of roles or validate a fixed message contract. Future Katty endpoints must never accept caller-supplied system/developer roles, arbitrary message arrays, provider options, tool definitions or model names.
6. **No private-data retrieval is present in the reviewed chat request path.** This is a useful current boundary, not a guarantee for future retrieval features. Any future knowledge source must be explicitly allowlisted and public-only for guest Katty; retrieved text and uploaded material must be labelled untrusted data, not instructions.
7. **No evidence in these files proves that every other frontend or backend feature is free of secrets or unsafe tool paths.** This audit is scoped to the named files and the reviewed AI route/adapter. It does not inspect live provider configuration, browser runtime traffic, deployment secrets or all repository integrations.

### 19.3 Required defense-in-depth design for Katty

- Keep system/developer instructions, persona configuration, safety policy, provider choice and output limits server-owned and versioned. Reject unknown request fields and never let the client choose a role, model, endpoint, tool, policy version or permission scope.
- Treat every user message, quoted passage, community post, uploaded file, public web page and retrieved document as untrusted data. Delimit and label such content; never promote embedded instructions to system/developer authority.
- Do not put API keys, service-role credentials, JWTs, passwords, hidden prompts, internal reasoning, moderation evidence or private account data in model context. Secrets must remain in backend configuration and be excluded from model-visible payloads and logs.
- Keep the first Katty release tool-free. If tools are introduced later, use a small server-side allowlist with strict typed schemas, per-tool authorization on every invocation, least-privilege service identities, ownership checks, bounded arguments and timeouts. A model's claim that an action is authorized is never authorization.
- Require explicit user confirmation for consequential actions (publishing, sending messages, deleting or changing user data, purchases, account changes). The backend must independently re-check permissions after confirmation; confirmation must not override policy or ownership.
- Never expose admin tools or admin context to Katty. A user saying “I am the owner/admin” or asking the model to change roles must have no effect on verified authorization.
- For any future retrieval or file access, enforce owner/public scope before fetching content, use fixed approved sources, block arbitrary URL fetches and internal-network/metadata targets, validate file type/size/path, and ensure one user's retrieved context cannot enter another user's request.
- Moderate both input and output, including voice transcription and text that will be spoken aloud. Add explicit handling for prompt-extraction requests, role-confusion attempts, instruction overrides, data-exfiltration requests and indirect injections in quoted/retrieved content. Pattern matching alone is insufficient.
- Return only a typed, minimal response contract. Never return raw provider payloads, hidden prompts, internal moderation rationale, tool traces or unapproved action instructions to the browser.
- Redact sensitive values from logs and errors. Keep moderation evidence separate from ordinary operational logs with narrow audited moderator access and a defined retention policy.
- Add a kill switch and fail-closed behavior for moderation, authorization, session-store or tool-authorization outages.

### 19.4 Required adversarial tests and release gate

Test direct and indirect injection in Russian and English, mixed languages, quoted text, Unicode/spacing obfuscation, role-play, fake “system” messages, requests to reveal hidden instructions, attempts to obtain API keys or another user's data, and instructions embedded in any future retrieved documents or uploads. Include benign discussion and educational quotation tests to reduce false positives.

For the tool-free MVP, verify that:
- client-supplied `system`/`developer` roles, message arrays, model overrides and tool/function definitions are rejected;
- a prompt cannot cause any backend action because no tool-execution capability is exposed;
- no secrets or private records are present in the provider message payload;
- cross-user and guest-session context cannot be loaded by changing IDs;
- both input and output moderation run, and moderation outage prevents an unchecked answer from being delivered;
- provider errors and logs do not disclose credentials or raw private prompts;
- a fake admin claim or instruction cannot change server-derived permissions.

If tools are ever added, require separate tests for per-tool authorization, owner checks, consent, replay/idempotency, argument validation, SSRF/file-path abuse, privilege escalation and audit records before enabling each tool.

**Release decision:** the reviewed current AI adapter has no tool/function execution and the current chat path does not retrieve private user data, which reduces the immediate impact of prompt injection. However, the existing system prompt and keyword filter are not sufficient protection for a public Katty service. Do not launch Katty until output moderation, strict server-owned message contracts, guest/account context isolation and the adversarial tests above are implemented and verified. Keep the first release tool-free.

This was a read-only source audit and documentation update. No AI route, provider adapter, moderation code, authentication code, database migration, live data, provider setting, production service or PR merge was changed.


## 20. Browser/client trust-boundary and request-routing audit — 2026-11-25

Read-only review of `app.js`, `index.html`, `supabase-config.js` and `sw.js` on branch `fix/supabase-key-compat-2026-11-23`. This review covers the current browser shell and AI Companion request path; Katty's own frontend does not yet exist.

### 20.1 Positive findings

- The browser configuration contains the Supabase project URL and a publishable key. The file explicitly identifies this as a browser-safe publishable key; it is not the Supabase service-role key. A publishable key is expected to be public and must rely on correct RLS and server authorization.
- The current AI Companion renders message text using `textContent`, not by inserting model/user message strings as HTML. The inspected dynamic `innerHTML` assignments use fixed markup and do not interpolate user-controlled message text.
- The service worker limits its custom cache handling to same-origin GET requests and does not intentionally cache API POST requests. It uses versioned shell caches and removes older caches during activation.
- The reviewed browser code does not expose the DeepSeek provider key. The AI request goes through the backend API.

### 20.2 High-priority finding: configurable API origin receives the user's Bearer token

The frontend reads its API base URL from localStorage key `pwa-studio-api-url` (or uses the Render URL by default). The Settings UI accepts any HTTPS URL and saves it in localStorage. The shared `apiRequest` helper then attaches the current Supabase access token as `Authorization: Bearer ...` to requests sent to that base URL.

This creates a sensitive trust-boundary problem: if the saved API URL is changed to an attacker-controlled HTTPS origin, subsequent authenticated API calls can send the user's Supabase Bearer token to that origin (subject to that server's CORS response). The URL is not currently restricted to a fixed allowlist of trusted backend origins before the token is attached. A malicious or compromised script that changes this localStorage value could exploit the same path.

**Required correction before Katty or wider public release:**
- For production builds, use a fixed server/API origin from trusted build-time configuration or a strict server-controlled allowlist. Do not let an arbitrary localStorage URL receive authenticated tokens.
- If local development overrides remain, permit only explicit localhost origins in development builds and never attach production credentials to them.
- Validate the parsed URL's scheme, origin and path before every request; reject credentials, fragments and unexpected path prefixes.
- Bind authorization headers only after the destination origin has passed the allowlist check. Do not allow arbitrary caller-provided `options.headers` to override or redirect authentication behavior.
- Consider separating public unauthenticated health requests from authenticated API requests.
- Add regression tests proving that an attacker-controlled URL, malformed URL, URL with user-info, alternate port, lookalike hostname, redirect or modified localStorage value never receives an Authorization header. Do not rely on CORS as the protection.

### 20.3 Additional browser security observations

1. **Supabase browser session is accessible to same-origin JavaScript.** The Supabase client is created with its normal browser configuration; the reviewed code does not configure a custom HttpOnly-cookie session. This is common for a browser SPA, but it means an XSS vulnerability could access the user's session. Keep all user-controlled content on safe DOM APIs, minimize third-party scripts, and consider a backend-for-frontend/HttpOnly-cookie architecture if the threat model warrants it.
2. **Third-party scripts are loaded from CDNs.** The page loads Tailwind's CDN script and Supabase JS from jsDelivr. The inspected tags do not show Subresource Integrity hashes, and the inspected HTML has no Content-Security-Policy meta tag. Static-host response headers were not inspected, so a host-level CSP may exist; this source review cannot confirm it. Before release, pin dependency versions, use integrity hashes where feasible, self-host critical assets where practical, and configure a restrictive CSP at the hosting layer (including explicit script/connect origins and no unsafe inline/eval unless justified).
3. **Fixed HTML snippets are not the same as safe rendering of future Katty content.** The current inspected `innerHTML` uses are static snippets. Keep Katty text, display names, room messages, moderation notes and retrieved content rendered with `textContent` or safe DOM construction. If rich Markdown is later supported, sanitize with a maintained allowlist sanitizer and test script/event-handler/URL payloads.
4. **Client-side visibility is not authorization.** Hiding the admin panel, changing navigation, editing localStorage, or altering JavaScript must never grant access. Backend JWT verification and `require_admin` remain the authority for every protected route.
5. **The AI Companion history is still browser-written.** The frontend inserts both user and assistant-role history rows directly through the Supabase client. The previously documented assistant-role forgery issue therefore remains relevant: a browser client must not be trusted to attest that an assistant response was genuinely generated. Katty messages must be persisted by a trusted backend only.
6. **No Katty guest session or Katty chat client exists in the reviewed frontend.** The current AI Companion requires sign-in and blocks guests at the UI. This is not a guest Katty implementation and must not be repurposed by simply removing the UI gate.
7. **Service-worker cache is a shell cache, not a security boundary.** Cached JavaScript can remain available offline until an updated worker activates; the current versioned cache strategy is helpful, but release procedures should verify activation/update behavior and ensure sensitive responses are never added to the shell cache.

### 20.4 Required tests and release gates

- API destination allowlist is enforced before any authenticated request; test lookalike domains, subdomains, alternate ports, redirects, malformed values and localStorage tampering.
- A guest request never carries an account Bearer token; an authenticated request never sends that token to an untrusted origin.
- Caller-supplied headers cannot replace authorization policy or smuggle credentials to a different destination.
- Stored XSS payloads in user messages, AI replies, display names, project titles, reports and moderator notes render as inert text.
- Markdown/HTML sanitization tests cover `<script>`, event handlers, `javascript:` URLs, SVG payloads and malformed markup if rich text is introduced.
- Backend endpoints continue to reject creators/guests from admin routes even when the frontend is modified.
- Katty guest session credentials are separate from Supabase account tokens, scoped only to Katty endpoints, short-lived and never stored in a shared/public identifier.
- Service-worker updates do not serve stale security-sensitive application code indefinitely, and API/private responses are not cached.
- Production CSP and CDN dependency integrity are verified from the deployed response headers/browser network panel before launch.

**Release decision:** the current browser shell has one high-priority issue to resolve before relying on it for authenticated AI requests: the configurable API URL can become the destination for a Bearer token without a trusted-origin allowlist. Fix and regression-test that boundary before implementing or enabling Katty. Keep browser rendering non-executable, keep backend authorization authoritative, and persist Katty replies only through the trusted server.

This was a source-only frontend audit and documentation update. No frontend code, API routing, CSP headers, CDN configuration, Supabase settings, live data, production service or PR merge was changed.


## 11. Browser API-origin trust-boundary fix — 2026-11-25

A branch-only frontend hardening change was committed after the audit:
- Production now uses the fixed https://pwa-studio-creative-ai.onrender.com API origin; the pwa-studio-api-url localStorage value is ignored outside localhost/127.0.0.1 development.
- Local development overrides are restricted to plain HTTP on the current local hostname, without credentials, query, fragment, or non-root path.
- API requests must be relative /api/... paths and are resolved and checked against the trusted origin before fetch.
- The application rejects caller-supplied Authorization headers; the Supabase bearer token is attached only by the trusted API request function.
- Fetch uses credentials: omit and redirect: error to avoid ambient credentials and redirected API requests.
- Production settings no longer allow editing the backend URL; the health-check button remains available.
- Added source-level regression tests and included them in the frontend GitHub Actions test workflow.

Scope and limitations:
- This is a source change on the existing review branch only. It has not been merged or deployed, so it does not yet protect the live site.
- Tests are regression checks over the source contract, not a browser penetration test or proof against same-origin XSS.
- Localhost override behavior and production deployment headers/CSP still require separate verification.
