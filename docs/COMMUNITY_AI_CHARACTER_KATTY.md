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
