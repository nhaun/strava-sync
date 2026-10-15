import time
from datetime import UTC, date, datetime

import httpx
import pytest

from strava_sync.config import Config
from strava_sync.main import choose_token, next_delay, run_once
from strava_sync.state import State

from .test_downloader import FIT, file_response
from .test_session import make_jwt

NOW = datetime(2025, 3, 10, 12, tzinfo=UTC)


def model(id_, start, latlng=True):
    return {"id": id_, "start_time": start, "has_latlng": latlng, "sport_type": "Ride"}


class FakeStrava:
    def __init__(self, models, me_status=302, export=None):
        self.models = models
        self.me_status = me_status
        self.export = export or (lambda id_: file_response(FIT, "a.fit"))
        self.downloads = []

    def __call__(self, request):
        path = request.url.path
        if path == "/me":
            if self.me_status != 302:
                return httpx.Response(self.me_status)
            return httpx.Response(302, headers={"Location": "https://www.strava.com/athletes/12345"})
        if path == "/athlete/training_activities":
            page = int(request.url.params["page"])
            per = int(request.url.params["per_page"])
            return httpx.Response(200, json={"models": self.models[(page - 1) * per : page * per]})
        if path.endswith("/export_original"):
            id_ = int(path.split("/")[2])
            self.downloads.append(id_)
            return self.export(id_)
        return httpx.Response(404)


def cfg(tmp_path, **kw):
    env = {"STRAVA_REMEMBER_TOKEN": make_jwt(), "WATCH_DIR": str(tmp_path / "watch"), "STATE_DIR": str(tmp_path / "state")}
    env.update(kw)
    return Config.from_env(env)


def run(config, fake, sleeps=None):
    state = State.load(config.state_dir)
    ok = run_once(
        config,
        state,
        transport=httpx.MockTransport(fake),
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
        now=lambda: NOW,
    )
    return ok, State.load(config.state_dir)


def test_first_run_without_backfill_downloads_nothing_then_new_ones(tmp_path):
    config = cfg(tmp_path)
    fake = FakeStrava([model(1, "2025-03-01T00:00:00Z")])
    ok, state = run(config, fake)
    assert ok
    assert fake.downloads == []
    assert state.since == NOW

    fake.models.insert(0, model(2, "2025-03-10T13:00:00Z"))
    ok, state = run(config, fake)
    assert fake.downloads == [2]
    assert state.downloaded_ids == {2}
    assert (config.watch_dir / "strava-2.fit").exists()
    assert (config.state_dir / "health").read_text().startswith("OK")
    assert state.last_success == NOW


def test_backfill_is_throttled_and_resumes(tmp_path):
    config = cfg(tmp_path, BACKFILL_SINCE="2025-03-02", MAX_DOWNLOADS_PER_RUN="2", DOWNLOAD_DELAY="1.5")
    fake = FakeStrava([model(i, f"2025-03-0{i}T08:00:00Z") for i in range(5, 0, -1)])
    sleeps = []
    ok, state = run(config, fake, sleeps)
    assert ok
    assert fake.downloads == [2, 3]
    assert sleeps == [1.5]
    assert state.since == datetime(2025, 3, 2, tzinfo=UTC)

    run(config, fake)
    run(config, fake)
    assert fake.downloads == [2, 3, 4, 5]


def test_activity_without_file_is_marked_skipped(tmp_path):
    config = cfg(tmp_path, BACKFILL_SINCE="2025-01-01")
    fake = FakeStrava([model(1, "2025-03-01T00:00:00Z", latlng=False)], export=lambda i: httpx.Response(404))
    ok, state = run(config, fake)
    assert ok
    assert state.skipped_ids == {1}
    run(config, fake)
    assert fake.downloads == [1]


def test_auth_failure_sets_health_fail(tmp_path):
    config = cfg(tmp_path)
    ok, _ = run(config, FakeStrava([], me_status=200))
    assert not ok
    assert (config.state_dir / "health").read_text().startswith("FAIL")


def test_partial_progress_is_kept_on_error(tmp_path):
    config = cfg(tmp_path, BACKFILL_SINCE="2025-01-01")
    fake = FakeStrava(
        [model(2, "2025-03-02T00:00:00Z"), model(1, "2025-03-01T00:00:00Z")],
        export=lambda i: file_response(FIT, "a.fit") if i == 1 else httpx.Response(429),
    )
    ok, state = run(config, fake)
    assert not ok
    assert state.downloaded_ids == {1}


def test_transient_error_keeps_health_ok_while_recent_success(tmp_path):
    config = cfg(tmp_path)
    state = State.load(config.state_dir)
    state.since = NOW
    state.mark_success(NOW)
    ok, _ = run(config, FakeStrava([], me_status=503))
    assert not ok
    assert (config.state_dir / "health").read_text().startswith("OK")


def test_choose_token_prefers_later_expiry():
    old = make_jwt(exp=int(time.time()) + 100)
    new = make_jwt(exp=int(time.time()) + 10_000)
    assert choose_token(old, None) == old
    assert choose_token(old, new) == new
    assert choose_token(new, old) == new
    assert choose_token(old, "garbage") == old


@pytest.mark.parametrize("failures,expected", [(0, 3600), (1, 7200), (2, 14400), (10, 21600)])
def test_next_delay(failures, expected):
    assert next_delay(3600, failures) == expected
