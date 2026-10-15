from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    remember_token: str
    sync_interval: int = 3600
    backfill_since: date | None = None
    max_downloads_per_run: int = 50
    download_delay: float = 3.0
    watch_dir: Path = Path("/watch")
    state_dir: Path = Path("/state")

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        token = env.get("STRAVA_REMEMBER_TOKEN", "").strip()
        if not token:
            raise ConfigError("STRAVA_REMEMBER_TOKEN is required (value of the strava_remember_token browser cookie)")

        backfill_raw = env.get("BACKFILL_SINCE", "").strip()
        try:
            backfill_since = date.fromisoformat(backfill_raw) if backfill_raw else None
        except ValueError:
            raise ConfigError(f"BACKFILL_SINCE must be a date in YYYY-MM-DD format, got {backfill_raw!r}") from None

        return cls(
            remember_token=token,
            sync_interval=_positive(env, "SYNC_INTERVAL", 3600, int),
            backfill_since=backfill_since,
            max_downloads_per_run=_positive(env, "MAX_DOWNLOADS_PER_RUN", 50, int),
            download_delay=_positive(env, "DOWNLOAD_DELAY", 3.0, float, allow_zero=True),
            watch_dir=Path(env.get("WATCH_DIR", "/watch")),
            state_dir=Path(env.get("STATE_DIR", "/state")),
        )


def _positive(env: Mapping[str, str], key: str, default, type_, allow_zero: bool = False):
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = type_(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from None
    if value < 0 or (value == 0 and not allow_zero):
        raise ConfigError(f"{key} must be positive, got {raw!r}")
    return value
