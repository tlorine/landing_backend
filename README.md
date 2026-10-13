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

## Структура

```text
app/
  api/
    errors.py                 # единый формат ошибок API
    v1/
      endpoints/
        health.py             # liveness/readiness
        requests.py           # POST /requests
      router.py
  core/
    config.py                 # настройки из окружения
    logging.py
  db/
    base.py
    session.py                # async engine и session factory
  models/
    service_request.py        # SQLAlchemy-модель заявки
    notification_outbox.py    # состояние доставки уведомлений
  repositories/
    service_requests.py
    notification_outbox.py
  schemas/
    service_request.py        # входная валидация и ответ
  services/
    submissions.py            # атомарное создание заявки + outbox
    telegram.py               # Telegram Bot API
    notification_worker.py    # очередь, повторы, восстановление зависших задач
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

## Подключение фронтенда

С обоих Next.js сайтов отправляй одинаковый JSON на абсолютный URL API, например `https://api.example.com/api/v1/requests`. В `source_site` можно передать `main-landing` / `ai-landing` или имя домена. Значение приходит с клиента, поэтому оно удобно для аналитики, но не является криптографически подтверждённым источником.

В `CORS_ORIGINS` укажи точные origin обоих сайтов — с `https://`, без пути и завершающего `/`, например:

```env
CORS_ORIGINS=["https://example.com","https://ai.example.com"]
```

CORS — это ограничение для браузеров, а не защита публичного API от скриптов или спама. Перед публичным запуском используй HTTPS и reverse proxy с ограничением частоты запросов; пример Nginx-конфига лежит в `deploy/nginx.example.conf`. Его нужно адаптировать под домен и TLS-сертификаты.

## Миграции и тесты

Миграция `0001_create_requests_and_outbox` применяется командой `alembic upgrade head` (Compose делает это при старте API). После изменения моделей создай миграцию командой `alembic revision --autogenerate -m "describe change"`, затем обязательно проверь сгенерированный файл перед применением.

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
