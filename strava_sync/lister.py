"""Lists activities via the endpoint behind strava.com/athlete/training."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .session import StravaSession

MAX_PAGES = 1000


@dataclass(frozen=True)
class Activity:
    id: int
    name: str
    start: datetime | None
    sport_type: str
    has_latlng: bool

    @classmethod
    def from_model(cls, m: dict[str, Any]) -> Activity:
        return cls(
            id=int(m["id"]),
            name=str(m.get("name") or ""),
            start=_parse_start(m),
            sport_type=str(m.get("sport_type") or m.get("type") or ""),
            has_latlng=bool(m.get("has_latlng", True)),
        )


def _parse_start(m: dict[str, Any]) -> datetime | None:
    for key in ("start_time", "start_date"):
        value = m.get(key)
        if not isinstance(value, str):
            continue
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


def list_new_activities(
    session: StravaSession, known_ids: set[int], since: datetime | None, per_page: int = 20
) -> list[Activity]:
    """Return activities that are not yet known and start at/after `since`, oldest first.

    Pages are fetched newest first; paging stops at the first page without any new candidate.
    """
    found: dict[int, Activity] = {}
    for page in range(1, MAX_PAGES + 1):
        data = session.get_json(
            "/athlete/training_activities",
            params={"new_activity_only": "false", "per_page": per_page, "page": page},
        )
        models = data.get("models") or []
        activities = [Activity.from_model(m) for m in models]
        reached_since = since is not None and any(a.start is not None and a.start < since for a in activities)
        candidates = [
            a
            for a in activities
            if a.id not in known_ids and (since is None or a.start is None or a.start >= since)
        ]
        for a in candidates:
            found[a.id] = a
        if not candidates or reached_since or len(models) < per_page:
            break
    min_dt = datetime.min.replace(tzinfo=UTC)
    return sorted(found.values(), key=lambda a: (a.start or min_dt, a.id))
