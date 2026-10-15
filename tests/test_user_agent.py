import pytest

from app.services.user_agent import UserAgentInfo, is_bot, parse_user_agent

CASES = [
    (  # iPhone Safari
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        UserAgentInfo("iOS", "Safari", "mobile"),
    ),
    (  # iPad Safari
        "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        UserAgentInfo("iOS", "Safari", "tablet"),
    ),
    (  # iPhone Chrome
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) CriOS/126.0.6478.54 Mobile/15E148 Safari/604.1",
        UserAgentInfo("iOS", "Chrome", "mobile"),
    ),
    (  # Android Chrome
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Mobile Safari/537.36",
        UserAgentInfo("Android", "Chrome", "mobile"),
    ),
    (  # Android tablet
        "Mozilla/5.0 (Linux; Android 13; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36",
        UserAgentInfo("Android", "Chrome", "tablet"),
    ),
    (  # Samsung Internet
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
        "SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36",
        UserAgentInfo("Android", "Samsung Internet", "mobile"),
    ),
    (  # Telegram in-app on Android
        "Mozilla/5.0 (Linux; Android 14; SM-A546B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.6478.71 "
        "Mobile Safari/537.36 Telegram-Android/11.2.3 (Samsung SM-A546B; Android 14; SDK 34)",
        UserAgentInfo("Android", "Telegram", "mobile"),
    ),
    (  # Telegram in-app on iOS
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Mobile/15E148 Telegram-iOS/10.14",
        UserAgentInfo("iOS", "Telegram", "mobile"),
    ),
    (  # Yandex Browser on Android
        "Mozilla/5.0 (Linux; Android 12; M2101K6G) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 YaBrowser/24.4.5.123.00 SA/3 Mobile Safari/537.36",
        UserAgentInfo("Android", "Yandex", "mobile"),
    ),
    (  # Yandex Browser on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 YaBrowser/24.6.0.0 Safari/537.36",
        UserAgentInfo("Windows", "Yandex", "desktop"),
    ),
    (  # Edge on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.2592.68",
        UserAgentInfo("Windows", "Edge", "desktop"),
    ),
    (  # Firefox on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        UserAgentInfo("Windows", "Firefox", "desktop"),
    ),
    (  # Firefox on Linux
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        UserAgentInfo("Linux", "Firefox", "desktop"),
    ),
    (  # macOS Safari
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        UserAgentInfo("macOS", "Safari", "desktop"),
    ),
    (  # Windows Chrome
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36",
        UserAgentInfo("Windows", "Chrome", "desktop"),
    ),
    (  # ChromeOS
        "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36",
        UserAgentInfo("ChromeOS", "Chrome", "desktop"),
    ),
    (  # Opera on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36 OPR/111.0.0.0",
        UserAgentInfo("Windows", "Opera", "desktop"),
    ),
    ("SomethingUnknown/1.0", UserAgentInfo("Other", "Other", "desktop")),
]


@pytest.mark.parametrize(("user_agent", "expected"), CASES)
def test_parse_user_agent(user_agent: str, expected: UserAgentInfo) -> None:
    assert parse_user_agent(user_agent) == expected
    assert not is_bot(user_agent)


@pytest.mark.parametrize(
    "user_agent",
    [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
        "TelegramBot (like TwitterBot)",
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "WhatsApp/2.23.20.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/126.0.0.0",
        "Mozilla/5.0 (Linux; Android 11) Chrome-Lighthouse",
        "curl/8.7.1",
        "python-requests/2.32.3",
        "python-httpx/0.28.1",
        "Go-http-client/2.0",
        "okhttp/4.12.0",
        "Mozilla/5.0+(compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)",
    ],
)
def test_bots_are_detected(user_agent: str) -> None:
    assert is_bot(user_agent)
