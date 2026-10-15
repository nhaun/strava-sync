from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STATE_FILE = "state.json"
HEALTH_FILE = "health"


@dataclass
class State:
    """Persistent sync state. Every mutation is written to disk immediately."""

    state_dir: Path
    downloaded_ids: set[int] = field(default_factory=set)
    skipped_ids: set[int] = field(default_factory=set)
    since: datetime | None = None
    last_success: datetime | None = None
    remember_token: str | None = None

    @classmethod
    def load(cls, state_dir: Path) -> State:
        path = state_dir / STATE_FILE
        if not path.exists():
            return cls(state_dir=state_dir)
        data = json.loads(path.read_text())
        return cls(
            state_dir=state_dir,
            downloaded_ids=set(data.get("downloaded_ids", [])),
            skipped_ids=set(data.get("skipped_ids", [])),
            since=_parse_dt(data.get("since")),
            last_success=_parse_dt(data.get("last_success")),
            remember_token=data.get("remember_token"),
        )

    @property
    def known_ids(self) -> set[int]:
        return self.downloaded_ids | self.skipped_ids

    def mark_downloaded(self, activity_id: int) -> None:
        self.downloaded_ids.add(activity_id)
        self.save()

    def mark_skipped(self, activity_id: int) -> None:
        self.skipped_ids.add(activity_id)
        self.save()

    def mark_success(self, when: datetime) -> None:
        self.last_success = when
        self.save()

    def save(self) -> None:
        data = {
            "since": self.since.isoformat() if self.since else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "remember_token": self.remember_token,
            "downloaded_ids": sorted(self.downloaded_ids),
            "skipped_ids": sorted(self.skipped_ids),
        }
        _atomic_write(self.state_dir / STATE_FILE, json.dumps(data, indent=2))

    def set_health(self, ok: bool, message: str) -> None:
        _atomic_write(self.state_dir / HEALTH_FILE, f"{'OK' if ok else 'FAIL'} {message}\n")


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
