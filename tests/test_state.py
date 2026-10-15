import json
from datetime import UTC, datetime

from strava_sync.state import State


def test_fresh_state(tmp_path):
    state = State.load(tmp_path)
    assert state.downloaded_ids == set()
    assert state.skipped_ids == set()
    assert state.since is None
    assert state.last_success is None
    assert state.remember_token is None
    assert state.known_ids == set()


def test_roundtrip(tmp_path):
    since = datetime(2025, 1, 1, tzinfo=UTC)
    state = State.load(tmp_path)
    state.since = since
    state.remember_token = "x.y.z"
    state.mark_downloaded(1)
    state.mark_skipped(2)
    state.mark_success(datetime(2025, 2, 1, tzinfo=UTC))

    loaded = State.load(tmp_path)
    assert loaded.downloaded_ids == {1}
    assert loaded.skipped_ids == {2}
    assert loaded.known_ids == {1, 2}
    assert loaded.since == since
    assert loaded.remember_token == "x.y.z"
    assert loaded.last_success == datetime(2025, 2, 1, tzinfo=UTC)


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    state = State.load(tmp_path)
    state.mark_downloaded(5)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]
    assert json.loads((tmp_path / "state.json").read_text())["downloaded_ids"] == [5]


def test_creates_state_dir(tmp_path):
    state = State.load(tmp_path / "nested")
    state.mark_downloaded(1)
    assert (tmp_path / "nested" / "state.json").exists()


def test_health(tmp_path):
    state = State.load(tmp_path)
    state.set_health(True, "synced")
    assert (tmp_path / "health").read_text().startswith("OK")
    state.set_health(False, "token expired")
    assert (tmp_path / "health").read_text() == "FAIL token expired\n"
