from datetime import date
from pathlib import Path

import pytest

from strava_sync.config import Config, ConfigError


def test_defaults():
    cfg = Config.from_env({"STRAVA_REMEMBER_TOKEN": "a.b.c"})
    assert cfg.remember_token == "a.b.c"
    assert cfg.sync_interval == 3600
    assert cfg.backfill_since is None
    assert cfg.max_downloads_per_run == 50
    assert cfg.download_delay == 3.0
    assert cfg.watch_dir == Path("/watch")
    assert cfg.state_dir == Path("/state")


def test_all_values():
    cfg = Config.from_env(
        {
            "STRAVA_REMEMBER_TOKEN": " a.b.c ",
            "SYNC_INTERVAL": "600",
            "BACKFILL_SINCE": "2025-01-31",
            "MAX_DOWNLOADS_PER_RUN": "10",
            "DOWNLOAD_DELAY": "1.5",
            "WATCH_DIR": "/tmp/w",
            "STATE_DIR": "/tmp/s",
        }
    )
    assert cfg.remember_token == "a.b.c"
    assert cfg.sync_interval == 600
    assert cfg.backfill_since == date(2025, 1, 31)
    assert cfg.max_downloads_per_run == 10
    assert cfg.download_delay == 1.5
    assert cfg.watch_dir == Path("/tmp/w")
    assert cfg.state_dir == Path("/tmp/s")


def test_missing_token():
    with pytest.raises(ConfigError, match="STRAVA_REMEMBER_TOKEN"):
        Config.from_env({})


@pytest.mark.parametrize(
    "key,value",
    [
        ("SYNC_INTERVAL", "abc"),
        ("SYNC_INTERVAL", "0"),
        ("BACKFILL_SINCE", "31.01.2025"),
        ("MAX_DOWNLOADS_PER_RUN", "0"),
        ("DOWNLOAD_DELAY", "x"),
    ],
)
def test_invalid_values(key, value):
    with pytest.raises(ConfigError, match=key):
        Config.from_env({"STRAVA_REMEMBER_TOKEN": "a.b.c", key: value})
