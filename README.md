# PWA Studio — Creative AI

Творческая веб-студия для разработки видеоидей и кинопроектов.

## Текущая архитектура

- **Frontend:** Vanilla JavaScript, HTML, CSS, Tailwind utilities; публикация через GitHub Pages.
- **Backend:** Python 3.12, FastAPI, LiteLLM; отдельное развёртывание через Render.
- **Authentication:** Supabase Auth; frontend использует только публичный publishable key.
- **Database / Storage:** Supabase SQL foundation and private storage policies. Cloud project CRUD and media upload UI are not implemented yet.

## Что уже реализовано

### Frontend
- Адаптивная PWA-оболочка, мобильная навигация, светлая и тёмная темы.
- Разделы студии: главная, создание видео, Миникиностудия, Prompt Studio, медиатека, голосовая мастерская, сценарий и сцены, AI Companion, личный кабинет, путеводитель и правила.
- Supabase sign-in, sign-up and password reset request.
- Mini Movie Studio: создание локальных черновиков, компактный список, редактирование параметров, копирование проекта, удаление с подтверждением, история версий и последовательные этапы сценария, персонажей, голосов и плана монтажа.
- Черновики Миникиностудии хранятся в localStorage отдельно для каждого вошедшего пользователя на конкретном устройстве.

### Backend
- FastAPI health endpoint.
- JWT verification against Supabase JWKS.
- Authenticated AI Companion and prompt-generation endpoints.
- LiteLLM adapter for configured OpenAI, DeepSeek, Anthropic or Ollama provider.
- Initial text safety checks. This is not full multimodal moderation.

## Важные ограничения

- Локальные проекты Миникиностудии пока не синхронизируются между устройствами и не являются облачными записями.
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

1. Облачный CRUD проектов и версий с проверкой владельца.
2. Загрузка и безопасное хранение медиафайлов в private Supabase Storage.
3. AI-сценарист и раскадровка с сохранением результатов в проекте.
4. Character Library, согласие на использование внешности и голоса, Voice Studio.
5. Подключение видеогенераторов, очереди задач, scene-level regeneration и MP4 export.
6. Комплексная модерация, лимиты, резервное копирование, безопасность и тестирование перед публичным запуском.

## Ссылки

- Frontend: https://lina1209.github.io/pwa-studio-creative-ai/
- Repository: https://github.com/Lina1209/pwa-studio-creative-ai
