"""Run with APP_ENV=test, no secrets or database connection needed."""

import json
from pathlib import Path

from app.main import app

schema = app.openapi()
# These descriptions are authored here instead of inherited from Python's
# version-dependent HTTP reason phrases, keeping the checked-in contract stable.
status_descriptions = {
    "413": "Payload exceeds the maximum request size.",
    "422": "Request validation failed.",
}
for path_item in schema["paths"].values():
    for operation in path_item.values():
        if not isinstance(operation, dict):
            continue
        for status, description in status_descriptions.items():
            response = operation.get("responses", {}).get(status)
            if response is not None:
                response["description"] = description
schema["paths"] = {
    path: value
    for path, value in schema["paths"].items()
    if path.startswith(("/api/v1/admin", "/api/v1/analytics"))
}
Path("contracts/analytics.openapi.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
)
