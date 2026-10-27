# LH47 · сайт с заявками и админ-панелью

Лендинг архитектурного бюро LH47 с формой заявки. Заявки сохраняются в Supabase, владельцу сразу приходит сообщение в Telegram, сотрудники обрабатывают заявки в админ-панели `/admin` (вход по паролю).

| Что | Где |
| --- | --- |
| Лендинг и форма (имя, телефон, комментарий) | `public/index.html` |
| Админ-панель: список (свежие сверху), карточка заявки, смена статуса, фильтр | `public/admin.html` |
| Приём заявки → Supabase → Telegram | `api/lead.py` |
| Вход / выход администратора (cookie на 7 дней, подписана HMAC) | `api/login.py` |
| Список и смена статуса (только после входа) | `api/leads.py` |
| Общие функции: проверка формы, Supabase REST, Telegram, сессия | `api/_lib.py` |
| Таблица в Supabase | `supabase.sql` |
| Локальный просмотр без Supabase и Telegram | `python3 dev_server.py` → http://localhost:8047, пароль `dev` |
| Проверки | `python3 -m unittest discover tests` |

Статусы заявки: «новая» (ставится автоматически), «в работе», «закрыта». Время в Telegram и в админке — по Кишинёву.

## Безопасность

- Все ключи — только в **Vercel → Settings → Environment Variables**. В коде и в репозитории их нет (`.env*` в `.gitignore`).
- Браузер не обращается к Supabase напрямую: всё идёт через функции `api/`, которые используют ключ service_role с сервера.
- В таблице включён Row Level Security без политик: публичный anon-ключ не может ни читать, ни писать.
- Без входа `/api/leads` отвечает 401, админка показывает только форму пароля.

## Переменные Vercel

| Переменная | Откуда взять |
| --- | --- |
| `SUPABASE_URL` | Supabase → Project Settings → Data API → Project URL |
| `SUPABASE_SERVICE_KEY` | Supabase → Project Settings → API Keys → `service_role` (secret) |
| `TELEGRAM_BOT_TOKEN` | @BotFather → `/newbot` → токен |
| `TELEGRAM_CHAT_ID` | ваш id: напишите боту `/start`, затем откройте `https://api.telegram.org/bot<токен>/getUpdates` → `message.chat.id` |
| `ADMIN_PASSWORD` | придумайте пароль для входа в `/admin` |

## Запуск (один раз)

1. **Supabase**: создайте проект → SQL Editor → вставьте `supabase.sql` → Run.
2. **Telegram**: создайте бота у @BotFather, напишите ему `/start`, узнайте свой chat id (см. таблицу).
3. **Vercel** (команда LH47): Add New → Project → импорт репозитория `lh47-zayavki`, Framework Preset **Other** → впишите 5 переменных → Deploy.
4. Отправьте тестовую заявку с сайта: она придёт в Telegram и появится в `/admin` с тем же именем и временем.
