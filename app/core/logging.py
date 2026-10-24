import logging

from app.core.config import settings

# Access log lines include the client address; visit beacons must never log it.
_PRIVATE_PATHS = ("/api/v1/visits", "/api/v1/analytics", "/api/v1/admin")


class _PrivatePathFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            return not args[2].startswith(_PRIVATE_PATHS)
        return True


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _PrivatePathFilter) for item in access_logger.filters):
        access_logger.addFilter(_PrivatePathFilter())
