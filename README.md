# Landing Requests Backend

Асинхронный backend для приёма заявок с двух (или большего числа) лендингов: **FastAPI + PostgreSQL + SQLAlchemy 2 async + Alembic + Telegram Bot API**.

Архитектура рассчитана на MVP, но не привязана к одному лендингу. Фронтенды отправляют один и тот же контракт, а `source_site` отмечает, откуда пришла заявка.

## Что уже есть

- `POST /api/v1/requests` — принимает и валидирует заявку.
- `service_requests` — хранит заявку в PostgreSQL.
- `notification_outbox` — в одной транзакции с заявкой сохраняет задание на Telegram-уведомление.
- Фоновый async worker отправляет уведомления и повторяет неудачные попытки с экспоненциальной задержкой.
- Если Telegram временно недоступен, заявка всё равно сохраняется, а API не заставляет пользователя отправлять форму повторно.
- Alembic-миграция, health endpoints, CORS-настройка, единый формат ошибок, Docker Compose, тесты валидации.
- Секреты задаются через `.env`; токен Telegram не выводится в логах.
- `POST /api/v1/visits` — анонимные визиты с лендингов (без cookies, IP не сохраняется).
- Команды бота `/visits`, `/sources`, `/help` в чате `TELEGRAM_CHAT_ID` — статистика за календарный период.

## Структура

```text
app/
  api/
    errors.py                 # единый формат ошибок API
    v1/
      endpoints/
        health.py             # liveness/readiness
        requests.py           # POST /requests
        visits.py             # POST /visits
      router.py
  bot/
    commands.py               # разбор команд бота
    formatting.py             # HTML-отчёты для Telegram
  core/
    config.py                 # настройки из окружения
    logging.py
  db/
    base.py
    session.py                # async engine и session factory
  models/
    service_request.py        # SQLAlchemy-модель заявки
    notification_outbox.py    # состояние доставки уведомлений
    site_visit.py             # визиты и соли дня
  repositories/
    service_requests.py
    notification_outbox.py
    site_visits.py            # запись визитов и агрегаты
  schemas/
    service_request.py        # входная валидация и ответ
    site_visit.py             # валидация визита
  services/
    submissions.py            # атомарное создание заявки + outbox
    telegram.py               # Telegram Bot API
    notification_worker.py    # очередь, повторы, восстановление зависших задач
    visits.py                 # запись визита и хэш посетителя
    user_agent.py             # ОС, браузер, устройство, фильтр ботов
    periods.py                # календарные периоды
    visit_stats.py            # статистика без зависимости от Telegram
    telegram_bot.py           # Bot API для команд
    bot_worker.py             # long-polling команд
    visit_retention.py        # удаление старых визитов и солей
migrations/
tests/
deploy/nginx.example.conf
```

## Быстрый запуск через Docker

1. Установи Docker Engine и Docker Compose plugin.
2. В каталоге проекта выполни:

   ```bash
   cp .env.example .env
   ```

3. В `.env` обязательно задай свой `POSTGRES_PASSWORD`. Для простоты этого шаблона используй URL-safe пароль из букв, цифр, `_` и `-`. Для production также укажи `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` и реальные домены фронтендов в `CORS_ORIGINS`.
4. Запусти:

   ```bash
   docker compose up --build -d
   docker compose logs -f api
   ```

Compose дождётся готовности PostgreSQL, применит Alembic-миграции и запустит API. Документация Swagger будет доступна на `http://localhost:8000/docs`, OpenAPI JSON — на `http://localhost:8000/openapi.json`. При `APP_ENV=production` документация API (`/docs`, `/redoc`, `/openapi.json`) отключена.

Остановка без удаления данных:

```bash
docker compose down
```

Удалять volume с базой (это **удалит данные заявок**) обычной командой `down` не нужно; `docker compose down -v` использовать только если действительно хочешь удалить базу.

## Запуск API локально без Docker-контейнера приложения

Нужны Python 3.12+ и PostgreSQL. Если запускаешь PostgreSQL через этот Compose, оставь сервис `db` включённым, а в `.env` используй адрес `localhost` в `DATABASE_URL`. При изменении `POSTGRES_PASSWORD` обнови и пароль в `DATABASE_URL`; для запуска через Compose адрес и пароль внутри контейнера подставляются автоматически.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
cp .env.example .env            # если ещё не сделал
alembic upgrade head
uvicorn app.main:app --reload
```

Не запускай одновременно Compose-сервис `api` и локальный `uvicorn` на одном порту. При разработке можно запускать только базу: `docker compose up -d db`.

## API-контракт

### `POST /api/v1/requests`

Пример запроса:

```json
{
  "name": "Иван",
  "budget": "до 100 000 ₽",
  "contact": "@demo_user",
  "description": "Нужен лендинг для IT-услуг и форма отправки заявок.",
  "source_site": "main-landing"
}
```

`name` и `budget` необязательны. `budget` — строка, чтобы поддерживать варианты вроде `от 50 000 до 100 000 ₽`, `обсудим` или `пока не определён`.

| Поле | Требования |
|---|---|
| `name` | Необязательная строка до 100 символов |
| `budget` | Необязательная строка до 100 символов |
| `contact` | Обязательный email, телефон (7–15 цифр) или Telegram username вида `@username` |
| `description` | Обязательная строка от 10 до 5000 символов |
| `source_site` | Обязательная строка до 255 символов: домен или заданный фронтендом ID сайта |

Успешный ответ — `201 Created`:

```json
{
  "id": "2b1c57db-bd8e-4ebc-8be5-7759f6d79c88",
  "status": "accepted",
  "created_at": "2026-10-13T08:30:00Z"
}
```

`id` в примере условный. Ответ означает, что заявка и задание на уведомление сохранены в базе. Он **не** обещает, что Telegram уже доставил сообщение: доставка идёт асинхронно.

Ошибки валидации возвращаются как `422`:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Проверьте введённые данные.",
    "details": [
      {"field": "contact", "message": "Укажите email, телефон или Telegram в формате @username."}
    ]
  }
}
```

Другие важные ответы: `503` — база временно недоступна; `500` — непредвиденная ошибка. Клиенту не раскрываются SQL, stack trace или внутренние URL.

Проверить API вручную:

```bash
curl -X POST http://localhost:8000/api/v1/requests \\
  -H 'Content-Type: application/json' \\
  -d '{"contact":"dev@example.com","description":"Нужен лендинг и форма заявки для сервиса.","source_site":"main-landing"}'
```

Health endpoints:

- `GET /api/v1/health/live` — процесс запущен.
- `GET /api/v1/health/ready` — проверяет подключение к PostgreSQL.

## Telegram

1. Создай бота через `@BotFather` и скопируй токен в `TELEGRAM_BOT_TOKEN`.
2. Напиши боту хотя бы одно сообщение (для личного чата обычно `/start`).
3. Получи `chat_id` своего личного чата или группы и укажи его в `TELEGRAM_CHAT_ID`. Токен — секрет: не публикуй ссылку с ним, не отправляй его в чаты и не коммить `.env`.
4. Перезапусти сервис: `docker compose up -d --build api`.

Если обе настройки пустые, приложение запускается без Telegram worker; заявки и задания на отправку всё равно сохраняются. После настройки Telegram и перезапуска worker подберёт ожидающие задания.

Ошибки доставки повторяются с увеличивающейся задержкой. Если процесс упадёт во время обработки, зависшая задача может быть подобрана повторно через пять минут. В редком случае сбоя между успешной отправкой в Telegram и отметкой в БД сообщение может прийти повторно — это стандартное ограничение доставки «как минимум один раз».

## Статистика посещений

### `POST /api/v1/visits`

Фронтенд отправляет один `navigator.sendBeacon` на загрузку страницы с `Content-Type: text/plain;charset=UTF-8` (без CORS preflight); `application/json` тоже принимается. Тело — JSON не больше 2 КБ:

```json
{"source_site":"studio-landing","path":"/en","locale":"en","device_type":"mobile",
 "referrer_host":"partner.example.org","utm_source":"telegram","utm_medium":"post","utm_campaign":"launch_oct"}
```

Обязательны только `source_site` и `path`. Ответ — `204 No Content`; ошибки: `400` (не JSON), `413` (больше 2 КБ), `422` (валидация), `429` (больше `VISITS_RATE_LIMIT_PER_MINUTE` в минуту с одного IP + User-Agent). Запросы без User-Agent и от ботов получают `204` и не записываются.

Сервер использует заголовки Cloudflare: `CF-IPCountry` — страна (`XX`/`T1` = не определено), `CF-Connecting-IP` — IP посетителя. Поэтому API должен быть доступен только через Cloudflare с включённым IP Geolocation: без прокси эти заголовки может подделать клиент.

**Приватность.** IP не сохраняется ни в БД, ни в логах (строки access-лога для `/api/v1/visits` отфильтрованы). Посетитель считается по `sha256(соль_дня || ip || UA || source_site)`; соль дня случайная и удаляется после вчерашнего дня, после чего хэш нельзя связать с IP. Поэтому «посетители» уникальны только в пределах суток. Визиты старше `VISITS_RETENTION_MONTHS` удаляются автоматически раз в 6 часов.

### Команды бота

Если заданы `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` и `TELEGRAM_COMMANDS_ENABLED=true`, API через long polling (`getUpdates`) отвечает в чате `TELEGRAM_CHAT_ID` (сообщения из других чатов игнорируются):

- `/visits [период]` — визиты, посетители, заявки и конверсия, страны, устройства, ОС, браузеры, язык;
- `/sources [период]` — источники переходов и UTM-кампании;
- `/help` — справка.

Период календарный по `STATS_TIMEZONE` (по умолчанию Москва), текущий день/неделя/месяц включены: `7d`/`7 дней` (до 366), `2w`/`2 недели` (до 52), `3m`/`3 месяца` (до 12). Без периода — 7 дней.

- `TELEGRAM_CHAT_ID` должен быть числовым id чата (не `@username`), иначе команды не будут совпадать с чатом.
- В группе с включённым privacy mode бот гарантированно видит команды вида `/visits@имя_бота`.
- Long polling несовместим с webhook: если на боте установлен webhook, в логах будет ошибка `409`; webhook автоматически не удаляется.

## Подключение фронтенда

С обоих Next.js сайтов отправляй одинаковый JSON на абсолютный URL API, например `https://api.example.com/api/v1/requests`. В `source_site` можно передать `main-landing` / `ai-landing` или имя домена. Значение приходит с клиента, поэтому оно удобно для аналитики, но не является криптографически подтверждённым источником.

В `CORS_ORIGINS` укажи точные origin обоих сайтов — с `https://`, без пути и завершающего `/`, например:

```env
CORS_ORIGINS=["https://example.com","https://ai.example.com"]
```

CORS — это ограничение для браузеров, а не защита публичного API от скриптов или спама. Перед публичным запуском используй HTTPS и reverse proxy с ограничением частоты запросов; пример Nginx-конфига лежит в `deploy/nginx.example.conf`. Его нужно адаптировать под домен и TLS-сертификаты.

## Миграции и тесты

Миграции `0001_create_requests_and_outbox` и `0002_site_visits` применяются командой `alembic upgrade head` (Compose делает это при старте API). После изменения моделей создай миграцию командой `alembic revision --autogenerate -m "describe change"`, затем обязательно проверь сгенерированный файл перед применением.

Запуск тестов:

```bash
pip install -r requirements-dev.txt
pytest
ruff check app tests migrations
```

## MVP-границы

- В этом шаблоне нет админки, списка заявок, авторизации или удаления заявок.
- `source_site` задаёт клиент и его можно подделать.
- Nginx-конфиг — образец, не готовая конфигурация с TLS.
- Для серьёзной нагрузки стоит вынести worker в отдельный процесс и добавить мониторинг очереди/ошибок доставки.
