import pytest

from app.bot.commands import Command, CommandError, parse_command
from app.services.periods import Period


@pytest.mark.parametrize(
    ("text", "period"),
    [
        ("/visits 7d", Period("day", 7)),
        ("/visits 7 дней", Period("day", 7)),
        ("/visits 1 день", Period("day", 1)),
        ("/visits 3 дня", Period("day", 3)),
        ("/visits 1d", Period("day", 1)),
        ("/visits 5д", Period("day", 5)),
        ("/visits 2 days", Period("day", 2)),
        ("/visits 2w", Period("week", 2)),
        ("/visits 2н", Period("week", 2)),
        ("/visits 1 неделя", Period("week", 1)),
        ("/visits 3 недели", Period("week", 3)),
        ("/visits 5 недель", Period("week", 5)),
        ("/visits 4нед", Period("week", 4)),
        ("/visits 1 week", Period("week", 1)),
        ("/visits 2 WEEKS", Period("week", 2)),
        ("/sources 3м", Period("month", 3)),
        ("/sources 1 месяц", Period("month", 1)),
        ("/sources 2 месяца", Period("month", 2)),
        ("/sources 6 месяцев", Period("month", 6)),
        ("/sources 2мес", Period("month", 2)),
        ("/sources 3M", Period("month", 3)),
        ("/sources 1 month", Period("month", 1)),
        ("/sources 12 months", Period("month", 12)),
        ("  /visits   7D  ", Period("day", 7)),
    ],
)
def test_period_syntax(text: str, period: Period) -> None:
    command = parse_command(text, "stats_bot")
    assert isinstance(command, Command)
    assert command.period == period


def test_command_names() -> None:
    assert parse_command("/visits 1d", None) == Command("visits", Period("day", 1))
    assert parse_command("/sources 1d", None) == Command("sources", Period("day", 1))
    assert parse_command("/help", None) == Command("help")
    assert parse_command("/start", None) == Command("help")


def test_default_period_is_seven_days() -> None:
    assert parse_command("/visits", None) == Command("visits", Period("day", 7))


def test_own_bot_suffix_is_accepted_case_insensitively() -> None:
    assert parse_command("/visits@Stats_Bot 2w", "stats_bot") == Command(
        "visits", Period("week", 2)
    )


@pytest.mark.parametrize("text", ["/visits@other_bot 7d", "/help@other_bot"])
def test_other_bot_suffix_is_ignored(text: str) -> None:
    assert parse_command(text, "stats_bot") is None


@pytest.mark.parametrize("text", ["hello", "", "/unknown", "visits 7d"])
def test_non_commands_are_ignored(text: str) -> None:
    assert parse_command(text, "stats_bot") is None


@pytest.mark.parametrize(
    "text",
    [
        "/visits 7",
        "/visits d",
        "/visits 7 лет",
        "/visits 0d",
        "/visits 367d",
        "/sources 13m",
        "/visits 53w",
        "/visits -1d",
        "/visits 7d extra",
    ],
)
def test_errors(text: str) -> None:
    result = parse_command(text, None)
    assert isinstance(result, CommandError)
    assert "Формат периода" in result.message
