import time

from app.core.config import Settings
from app.services.bot_worker import TelegramCommandWorker
from app.services.telegram_bot import TelegramApiError

CHAT_ID = "-1001234567890"


class FakeApi:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, int | None]] = []

    async def send_message(self, chat_id, text, reply_to_message_id=None) -> None:
        self.sent.append((str(chat_id), text, reply_to_message_id))


class FakeStats:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def visitors_report(self, period, now):
        self.calls += 1
        if self.fail:
            raise RuntimeError("db down")
        from tests.test_bot_formatting import visitors_report

        return visitors_report()


def make_worker(stats=None, clock=lambda: 0.0):
    settings = Settings(_env_file=None, telegram_bot_token="1:x", telegram_chat_id=CHAT_ID)
    api = FakeApi()
    worker = TelegramCommandWorker(api, stats or FakeStats(), settings, clock=clock)
    worker._bot_username = "stats_bot"
    return worker, api


def update(text: str, chat_id: str = CHAT_ID, age: int = 0, message_id: int = 7) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": message_id,
            "date": int(time.time()) - age,
            "chat": {"id": int(chat_id)},
            "text": text,
        },
    }


async def test_answers_command_in_configured_chat() -> None:
    worker, api = make_worker()
    await worker.handle_update(update("/visits 7d"))
    [(chat, text, reply_to)] = api.sent
    assert (chat, reply_to) == (CHAT_ID, 7)
    assert "Посещения" in text


async def test_ignores_other_chats_old_messages_and_plain_text() -> None:
    worker, api = make_worker()
    await worker.handle_update(update("/visits", chat_id="42"))
    await worker.handle_update(update("/visits", age=121))
    await worker.handle_update(update("hello"))
    await worker.handle_update(update("/visits@other_bot"))
    await worker.handle_update({"update_id": 2, "edited_message": {}})
    assert api.sent == []


async def test_command_error_gets_hint() -> None:
    worker, api = make_worker()
    await worker.handle_update(update("/visits 99 лет"))
    assert "Формат периода" in api.sent[0][1]


async def test_stats_failure_is_reported_without_details() -> None:
    worker, api = make_worker(stats=FakeStats(fail=True))
    await worker.handle_update(update("/visits"))
    assert api.sent[0][1] == "Не удалось получить статистику, попробуйте позже."


async def test_one_command_per_three_seconds() -> None:
    now = [100.0]
    stats = FakeStats()
    worker, api = make_worker(stats=stats, clock=lambda: now[0])
    await worker.handle_update(update("/visits"))
    now[0] = 102.0
    await worker.handle_update(update("/help"))
    now[0] = 103.5
    await worker.handle_update(update("/help"))
    assert [text for _, text, _ in api.sent][1] == "Подождите пару секунд."
    assert "/sources" in api.sent[2][1]
    assert stats.calls == 1


async def test_send_failure_does_not_raise() -> None:
    worker, api = make_worker()

    async def failing_send(*args, **kwargs):
        raise TelegramApiError("sendMessage: rejected with HTTP 400.", 400)

    api.send_message = failing_send
    await worker.handle_update(update("/help"))
