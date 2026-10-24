"""Run with APP_ENV=test, no secrets or database connection needed."""

import json
from pathlib import Path

from app.main import app

schema = app.openapi()
schema["paths"] = {
    path: value
    for path, value in schema["paths"].items()
    if path.startswith(("/api/v1/admin", "/api/v1/analytics"))
}
Path("contracts/analytics.openapi.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
)
