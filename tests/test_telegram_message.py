from app.services.telegram import TelegramNotifier


def test_long_description_is_truncated_only_in_telegram_message() -> None:
    request_data = {
        "id": "request-id",
        "name": None,
        "budget": None,
        "contact": "dev@example.com",
        "description": "x" * 5000,
        "source_site": "main-landing",
        "created_at": "2026-10-13T08:30:00+00:00",
    }

    message = TelegramNotifier._format_message(request_data)

    assert len(message) < 4096
    assert "описание обрезано только в уведомлении" in message
    assert "x" * 2800 in message
