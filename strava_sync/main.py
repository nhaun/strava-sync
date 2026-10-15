"""Entry point: periodically downloads new Strava activities into the watch folder."""

from __future__ import annotations

import logging
import signal
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from .config import Config, ConfigError
from .downloader import download_activity
from .lister import list_new_activities
from .session import AuthExpiredError, RateLimitError, StravaError, StravaSession, parse_remember_token
from .state import State

log = logging.getLogger("strava_sync")

MAX_BACKOFF = 6 * 3600
UNHEALTHY_AFTER_FAILED_INTERVALS = 6


def choose_token(env_token: str, stored_token: str | None) -> str:
    """Use the token that expires last: Strava may rotate it, but the user may also set a fresh one."""
    if not stored_token:
        return env_token
    try:
        stored_exp = parse_remember_token(stored_token)[1]
    except AuthExpiredError:
        return env_token
    try:
        env_exp = parse_remember_token(env_token)[1]
    except AuthExpiredError:
        return stored_token
    return stored_token if stored_exp > env_exp else env_token


def next_delay(interval: int, consecutive_failures: int) -> int:
    return min(interval * 2**consecutive_failures, max(interval, MAX_BACKOFF))


def run_once(
    config: Config,
    state: State,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> bool:
    """Run one sync cycle. Returns True on success."""
    started = now()
    if state.since is None:
        if config.backfill_since:
            state.since = datetime.combine(config.backfill_since, datetime.min.time(), tzinfo=UTC)
            log.info("first run: backfilling activities since %s", state.since.date())
        else:
            state.since = started
            log.info("first run: only activities started after %s will be downloaded", started.isoformat())
        state.save()

    session = None
    try:
        session = StravaSession(choose_token(config.remember_token, state.remember_token), transport=transport)
        session.login()
        pending = list_new_activities(session, state.known_ids, state.since)
        batch = pending[: config.max_downloads_per_run]
        if pending:
            log.info("%d new activities found, downloading %d", len(pending), len(batch))
        for i, activity in enumerate(batch):
            if i:
                sleep(config.download_delay)
            path = download_activity(session, activity, config.watch_dir)
            if path is None:
                state.mark_skipped(activity.id)
            else:
                state.mark_downloaded(activity.id)
                log.info("downloaded activity %s (%s, %s) -> %s", activity.id, activity.sport_type, activity.start, path.name)
        if len(pending) > len(batch):
            log.info("%d activities left for the next runs", len(pending) - len(batch))
        state.mark_success(started)
        state.set_health(True, f"last sync {started.isoformat()}")
        return True
    except AuthExpiredError as exc:
        log.error(
            "authentication failed: %s. Log in to strava.com in a browser, copy the strava_remember_token "
            "cookie into STRAVA_REMEMBER_TOKEN and restart the container.",
            exc,
        )
        state.set_health(False, f"auth failed: {exc}")
        return False
    except (StravaError, httpx.HTTPError, ValueError) as exc:
        level = logging.WARNING if isinstance(exc, RateLimitError) else logging.ERROR
        log.log(level, "sync failed: %s: %s", type(exc).__name__, exc)
        limit = timedelta(seconds=config.sync_interval * UNHEALTHY_AFTER_FAILED_INTERVALS)
        healthy = state.last_success is not None and started - state.last_success < limit
        state.set_health(healthy, f"last error: {exc}")
        return False
    finally:
        if session is not None:
            if session.remember_token != config.remember_token and session.remember_token != state.remember_token:
                log.info("Strava rotated the remember token, storing the new one")
                state.remember_token = session.remember_token
                state.save()
            session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # PID 1 in a container ignores SIGTERM unless a handler is installed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    try:
        config = Config.from_env()
    except ConfigError as exc:
        log.error("invalid configuration: %s", exc)
        sys.exit(2)

    state = State.load(config.state_dir)
    log.info("strava-sync started, interval %ss, watch dir %s", config.sync_interval, config.watch_dir)
    failures = 0
    while True:
        failures = 0 if run_once(config, state) else failures + 1
        delay = next_delay(config.sync_interval, failures)
        log.info("next sync in %d minutes", delay // 60)
        time.sleep(delay)


if __name__ == "__main__":
    main()
