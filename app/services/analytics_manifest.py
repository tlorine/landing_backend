import json
from pathlib import Path

from app.schemas.analytics import AnalyticsEventCreate

MANIFEST = json.loads((Path(__file__).resolve().parents[2] / "contracts/cases.json").read_text())
CASES = {entry["id"]: entry for entry in MANIFEST["cases"]}


def validate_event(event: AnalyticsEventCreate) -> None:
    home = "/en" if event.locale == "en" else "/"
    if event.case_id is not None and event.case_id not in CASES:
        raise ValueError("unknown case_id")
    case_path = ("/en" if event.locale == "en" else "") + f"/cases/{event.case_id}"
    if event.event_type == "case_open":
        valid = (
            event.path == home
            and event.case_id is not None
            and event.placement == "home_cases"
            and event.navigation_id is not None
            and event.link_id is None
        )
    elif event.event_type == "case_outbound_click":
        valid = (
            event.case_id is not None
            and event.path == case_path
            and event.placement == "case_project"
            and event.link_id == "project_primary"
            and CASES[event.case_id]["has_outbound_link"]
        )
    else:
        valid = (
            event.path == (case_path if event.case_id else home)
            and event.link_id is None
            and event.placement is None
        )
    if not valid:
        raise ValueError("event path, case, link or placement mismatch")
