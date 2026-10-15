import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings(cors_origins: list[str]) -> Settings:
    return Settings(_env_file=None, cors_origins=cors_origins)


def test_cors_origins_trailing_slash_is_removed() -> None:
    settings = make_settings(["https://front.example.com/", " http://localhost:3000 "])
    assert settings.cors_origins == ["https://front.example.com", "http://localhost:3000"]


@pytest.mark.parametrize(
    "origin",
    ["*", "front.example.com", "https://front.example.com/form", "ftp://front.example.com"],
)
def test_cors_origins_rejects_wildcard_and_invalid_values(origin: str) -> None:
    with pytest.raises(ValidationError):
        make_settings([origin])


def test_cors_origins_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.trycloudflare.com","https://b.example.com"]')
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["https://a.trycloudflare.com", "https://b.example.com"]
