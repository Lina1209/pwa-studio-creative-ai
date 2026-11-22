# Счётчик посещений PWA Studio

## Что отображается на главной

- **Посещений за всё время** — накопительное число загрузок страниц, зарегистрированных после установки миграции 0027.
- **Сегодня** — загрузки страниц за текущие сутки UTC.
- В API также доступны приблизительные уникальные посетители за сегодня, просмотры за 7 и 30 дней.

Это именно просмотры страниц (page views), а не число разных людей. Один посетитель может создать несколько просмотров. Блок на главной показывает общий накопительный счётчик и число за сегодня.

## Архитектура

- Frontend `analytics.js` создаёт случайный first-party token на текущий UTC-день и UUID события.
- Backend принимает событие через `POST /api/analytics/visit`.
- Сервер хеширует токен SHA-256 и отправляет его в Supabase RPC с service-role credentials; секреты не попадают в браузер.
- PostgreSQL атомарно увеличивает lifetime total и дневной агрегат.
- Повторная доставка одного event UUID не увеличивает счётчики повторно.
- Публичный endpoint `GET /api/analytics/stats` отдаёт только агрегированные числа.
- Owner-only endpoint `GET /api/admin/analytics/site-visits` защищён `require_admin`.
- Таблицы доступны только service_role; anon/authenticated не имеют прямого доступа.
- IP, email, auth user ID, user-agent, prompt, media names and precise location are not stored.
- Deduplication event rows are pruned opportunistically after 7 days; daily visitor hashes after 2 days. Daily aggregates and lifetime total remain.

## Ограничения и честная интерпретация

- Счётчик начинает считать только после применения миграции 0027 и развёртывания backend + frontend из рабочей ветки. Он не импортирует посещения до установки.
- Lifetime total — сумма принятых page-view events, а не уникальных людей.
- Уникальные посетители — приблизительная оценка на день; очистка браузерного хранилища, приватный режим, блокировщики и разные устройства могут считать одного человека несколько раз.
- Без отдельного CDN/WAF rate limit публичный endpoint можно искусственно накрутить. Перед публичным production-запуском включить edge rate limiting/bot filtering и мониторинг аномалий. Не использовать эти цифры как биллинговую или финансовую метрику.
- Текущий frontend считает один просмотр при загрузке документа. Внутренние SPA-переходы не увеличивают просмотры до отдельного route-change hook; это намеренно консервативный подсчёт.
- Сутки считаются по UTC.

## Включение

1. Проверить migration 0027 в staging и применить её к целевой Supabase базе вручную по обычному release-процессу.
2. Убедиться, что backend имеет `SUPABASE_URL` и server-only `SUPABASE_SERVICE_ROLE_KEY`.
3. Развернуть backend с новыми маршрутами и frontend с `analytics.js`.
4. Проверить `GET /api/analytics/stats`, одну тестовую загрузку, повтор одного event UUID и отсутствие доступа anon к таблицам/RPC.
5. Проверить owner-only маршрут под admin и под обычным creator (ожидается 403).
6. Включить rate limiting на CDN/WAF и проверить исключение preview/dev traffic.

Миграция не применяется автоматически этим коммитом. Production не менялся.
