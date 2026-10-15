from __future__ import annotations

import re
from dataclasses import dataclass

# Only a prefix is inspected: real browser UAs are far shorter, and it bounds regex work.
_MAX_UA_LENGTH = 1024

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|"
    r"whatsapp|telegrambot|vkshare|curl|wget|python-requests|httpx|aiohttp|go-http-client|"
    r"java/|okhttp|monitor|uptime",
    re.IGNORECASE,
)

# Order matters: more specific patterns come first.
_OS_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"iPhone|iPad|iPod"), "iOS"),
    (re.compile(r"Android"), "Android"),
    (re.compile(r"CrOS"), "ChromeOS"),
    (re.compile(r"Windows"), "Windows"),
    (re.compile(r"Mac OS X|Macintosh"), "macOS"),
    (re.compile(r"Linux"), "Linux"),
)
_BROWSER_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Telegram"), "Telegram"),
    (re.compile(r"YaBrowser"), "Yandex"),
    (re.compile(r"SamsungBrowser"), "Samsung Internet"),
    (re.compile(r"Edg(?:A|iOS)?/"), "Edge"),
    (re.compile(r"OPR/|Opera"), "Opera"),
    (re.compile(r"Firefox|FxiOS"), "Firefox"),
    (re.compile(r"Chrome|CriOS"), "Chrome"),
    (re.compile(r"Safari"), "Safari"),
)
# Anchored lookahead: "Mobile" anywhere means a phone, even when "Android" appears again later
# (e.g. "... Mobile Safari/537.36 Telegram-Android/11.2").
_TABLET_RE = re.compile(r"iPad|Tablet|^(?!.*Mobile).*Android", re.DOTALL)
_MOBILE_RE = re.compile(r"Mobi|iPhone|Android")


@dataclass(frozen=True, slots=True)
class UserAgentInfo:
    os: str
    browser: str
    device_type: str


def is_bot(user_agent: str) -> bool:
    return _BOT_RE.search(user_agent[:_MAX_UA_LENGTH]) is not None


def _first_match(rules: tuple[tuple[re.Pattern[str], str], ...], user_agent: str) -> str:
    for pattern, name in rules:
        if pattern.search(user_agent):
            return name
    return "Other"


def detect_device_type(user_agent: str) -> str:
    user_agent = user_agent[:_MAX_UA_LENGTH]
    if _TABLET_RE.search(user_agent):
        return "tablet"
    if _MOBILE_RE.search(user_agent):
        return "mobile"
    return "desktop"


def parse_user_agent(user_agent: str) -> UserAgentInfo:
    user_agent = user_agent[:_MAX_UA_LENGTH]
    return UserAgentInfo(
        os=_first_match(_OS_RULES, user_agent),
        browser=_first_match(_BROWSER_RULES, user_agent),
        device_type=detect_device_type(user_agent),
    )
