# PWA STUDIO — TECH LIBRARY
## Библиотека технологий и идей

**Назначение:** собирать интересные открытые проекты, AI-инструменты, библиотеки, технологии и дизайнерские решения для развития PWA Studio Creative AI.

### Правила библиотеки

1. Сохраняем официальные ссылки на проекты.
2. Изучаем возможности, лицензии и зависимости.
3. Проверяем совместимость с архитектурой PWA Studio.
4. Не копируем код без проверки безопасности и лицензии.
5. Ничего не внедряем без отдельного решения.
6. Приоритет — безопасность, доступность и экономичность.

---

## Запись № 001 — GodMode

- **Проект:** GodMode
- **Разработчик:** smol-ai
- **Репозиторий:** https://github.com/smol-ai/GodMode
- **Лицензия:** MIT (указана в репозитории; перед использованием конкретного кода и зависимостей перепроверить)
- **Статус:** изучен; идеи сохранены для возможного использования.

### Что умеет проект

- Открывает несколько AI-веб-приложений в отдельных панелях.
- Позволяет сравнивать результаты разных AI-сервисов.
- Поддерживает несколько рабочих панелей и изменение их расположения.
- Даёт идеи для улучшения промптов и выбора AI-инструмента.

### Идеи для PWA Studio

1. **AI LAB** — сравнение результатов DeepSeek и Gemini для одного запроса.
2. **PROMPT CRITIC** — анализ запроса пользователя и предложения по улучшению промпта.
3. **MULTI-PANEL WORKSPACE** — сравнение нескольких вариантов сценария, изображения или идеи.
4. **AI MODEL SELECTOR** — выбор модели под конкретную задачу.
5. **LOCAL AI — перспектива** — изучение локальных моделей в будущем.

### Безопасность и ограничения

- Сохранять серверную обработку запросов; не раскрывать API-ключи в браузере.
- Передавать данные дополнительной модели только с согласия пользователя.
- Учитывать стоимость запросов и ограничивать параллельные генерации.
- Не переносить чужую авторизацию или управление аккаунтами.
- Проверять лицензию и зависимости перед использованием кода.

### Потенциальная польза

Развить PWA Studio в творческую платформу, где пользователь может получать, сравнивать, улучшать и объединять идеи нескольких нейросетей.

**Приоритет внедрения:** средний — после завершения аудита безопасности и проверки экономики AI-генераций.


---

## Запись № 002 — Strix

- **Проект:** Strix — open-source AI penetration testing tool.
- **Разработчик:** usestrix.
- **Репозиторий:** https://github.com/usestrix/strix
- **Документация:** https://docs.strix.ai
- **Лицензия:** Apache-2.0 (проверено по метаданным проекта; перед использованием конкретных компонентов и зависимостей перепроверять).
- **Проверенная версия:** v1.7.1 (по состоянию на 27 ноября 2026 года).
- **Статус:** изучен предварительно; НЕ установлен и НЕ запускался. Сохранён для будущего контролируемого тестирования.
- **Зрелость:** проект обозначен разработчиками как Alpha.

### Назначение и возможности

Strix — инструмент для динамического тестирования безопасности приложений с помощью AI-агентов. Он может выполнять разведку, проверять API и авторизацию, пытаться подтвердить уязвимости и формировать отчёты с доказательствами и рекомендациями по исправлению.

### Потенциальная польза для PWA Studio

1. Проверка разграничения доступа между гостем, обычным пользователем и администратором.
2. Проверка доступа к чужим проектам, диалогам, медиафайлам и отчётам (IDOR / broken access control).
3. Проверка API и маршрутов авторизации.
4. Поиск потенциальных SQL-инъекций и XSS.
5. Проверка ограничений кредитов, тарифов и лимитов генерации на предмет обхода.
6. Проверка rate limiting и устойчивости к злоупотреблениям.
7. Подготовка отчёта с воспроизводимыми доказательствами и рекомендациями.

### Предварительная проверка ошибок и ограничений

При просмотре репозитория и открытых GitHub Issues обнаружены сообщения пользователей о проблемах, которые необходимо учитывать:

- **Issue #1833:** сообщается о конфликте двух параллельных сканирований на одной машине — один запуск может удалить контейнер другого.
- **Issue #1808:** сообщается о потере вывода команд в Docker на Windows; это может мешать агенту читать файлы и завершать проверку.
- В репозитории присутствуют и другие открытые сообщения об ошибках. Их статус и исправление нужно перепроверять перед каждым использованием.
- В метаданных Python-пакета проект обозначен как Alpha; это не следует считать зрелым и полностью предсказуемым инструментом.

Эти пункты — зарегистрированные сообщения пользователей, а не утверждение, что ошибки проявляются во всех системах или остаются неисправленными в каждой последующей версии.

### Технические требования и стоимость

- Для локального запуска требуется Docker.
- Нужен API-ключ поддерживаемого LLM-провайдера; сами AI-запросы могут создавать расходы.
- В метаданных текущего пакета указано требование Python >= 3.12.
- Перед запуском следует проверить актуальную документацию, совместимость ОС и Docker, выбранную модель, лимиты и стоимость.
- Не запускать несколько сканирований одновременно, пока поведение параллельных запусков не проверено в изолированной среде.

### Правила безопасного применения

1. Использовать только для собственных систем или при наличии явного письменного разрешения.
2. Первое тестирование PWA Studio проводить только на отдельной staging-копии, не на рабочем сайте.
3. До тестирования сделать резервные копии БД и файлов; использовать тестовые аккаунты и данные.
4. Ограничить область проверки конкретным тестовым доменом, API и разрешёнными действиями.
5. Не передавать инструменту production-секреты, реальные пользовательские данные и ключи с широкими правами.
6. Учитывать, что активная проверка может эксплуатировать найденные уязвимости и изменять состояние тестовой системы.
7. Не применять автоматическое исправление (auto-fix) без ручного анализа diff и отдельного согласования.
8. После проверки изучить отчёты, логи и созданные контейнеры; убедиться, что тестовая среда восстановлена.

### Решение по проекту

**Потенциальная ценность:** высокая для независимого аудита авторизации, API и бизнес-ограничений PWA Studio.

**Приоритет:** высокий для будущего изучения, но запуск отложен до завершения текущего аудита безопасности и подготовки изолированной тестовой копии.

**Текущий статус внедрения:** не интегрировать в продукт и не запускать на production. Сначала отдельно оценить безопасность самого инструмента, его зависимости, передачу данных и фактическую совместимость с нашей инфраструктурой.

---

## Будущие разделы библиотеки

1. AI-модели и интеллектуальные агенты.
2. Генерация изображений и видео.
3. Музыка, голос и звук.
4. Видеомонтаж и мини-киностудии.
5. Prompt Engineering.
6. Интерфейсы и дизайн.
7. Безопасность и защита данных.
8. Аналитика и оптимизация расходов.
9. Открытые библиотеки и GitHub-проекты.
10. Экспериментальные технологии.

**Главный принцип:** берём лучшее из технологий, но создаём собственную экосистему PWA Studio.

- [Generation Jobs contract](GENERATION_JOBS_CONTRACT.md) — inactive job lifecycle, durable queue, cancellation, retry, billing, and go-live gates.
- [Generation Credits Ledger contract](GENERATION_CREDITS_LEDGER_CONTRACT.md) — design-only immutable ledger, atomic reservations, idempotent settlement/release, and reconciliation. No wallet or billing implementation is active.


## Security review records

- [API authentication and object-authorization review](API_AUTHORIZATION_SECURITY_REVIEW.md) — JWT validation, admin identity, owner-scoped object access, Storage policies, and isolated two-user tests. Status: source review only; cloud/API handoff remains NO-GO.
- [Reference asset security review](REFERENCE_ASSET_SECURITY_REVIEW.md) — local-first references, file validation limits, owner isolation, private Storage, upload compensation, and generation/chat boundary. Status: source review only; cloud/provider handoff remains NO-GO.
- [Provider attempt and reconciliation contract](GENERATION_PROVIDER_RECONCILIATION_CONTRACT.md) — durable provider attempts, ambiguous outcomes, cancellation races, reconciliation leases, audit evidence, and credit holds. Status: design only; no worker or billing activation.

- [Katty visual identity passport](KATTY_VISUAL_IDENTITY_PASSPORT.md) and [machine-readable identity manifest](../../assets/characters/katty/identity.v1.json) — canonical appearance and cross-tool continuity.
- [Katty 2D layer and motion contract](KATTY_2D_LAYER_AND_MOTION_CONTRACT.md) and [layer manifest](../../assets/characters/katty/2d-layers.v1.json) — semantic face, hair, clothing and accessory layers; static fallback and reduced-motion rules. Design-only, no rig/runtime yet.
- [Katty expression system contract](KATTY_EXPRESSION_SYSTEM_CONTRACT.md) and [expression manifest](../../assets/characters/katty/expressions.v1.json) — versioned expression vocabulary and future 2D/3D rig requirements; design-only, no runtime animation.
- [Profile Avatar Selection contract](PROFILE_AVATAR_SELECTION_CONTRACT.md) — product requirements for free standard 2D categories, a separate real-3D collection, mobile selection, Katty identity continuity, and owner-scoped custom-avatar safety.
- [Profile avatar implementation audit](PROFILE_AVATAR_IMPLEMENTATION_AUDIT.md) — nine free 2D SVG avatars, responsive picker, owner-fenced persistence, community rendering, additive migration draft, and verified CI.
- [Profile avatar 3D architecture](PROFILE_AVATAR_3D_ARCHITECTURE.md) — design-only 3D model validation, renderer readiness, mobile/accessibility requirements, and explicit gates before enabling 3D.
- Shared local catalogue metadata lives in `profile-avatar-catalog.js`; the `katty-katarina` identity key is a continuity hint, not a profile-to-character foreign key. Profile avatars remain separate from Character Library records.
- [Katty visual identity passport](KATTY_VISUAL_IDENTITY_PASSPORT.md) — canonical face, hair, eyes, freckles, wardrobe, accessories, palette, allowed variations, and 2D/3D continuity rules. Machine-readable source: `assets/characters/katty/identity.v1.json`.
