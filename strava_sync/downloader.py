"""Downloads activity files into the watch folder."""

from __future__ import annotations

import gzip
import logging
import os
import tempfile
from pathlib import Path

from .lister import Activity
from .session import NotFoundError, StravaError, StravaSession

log = logging.getLogger(__name__)


def detect_format(content: bytes) -> str | None:
    if len(content) >= 12 and content[8:12] == b".FIT":
        return "fit"
    head = content[:2048].lstrip()
    if head.startswith(b"<"):
        if b"<gpx" in head:
            return "gpx"
        if b"<TrainingCenterDatabase" in head:
            return "tcx"
    return None


def _decode(content: bytes) -> tuple[bytes, str | None]:
    if content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except (OSError, EOFError):
            return content, None
    return content, detect_format(content)


def download_activity(session: StravaSession, activity: Activity, watch_dir: Path) -> Path | None:
    """Download the original file (FIT/TCX/GPX) or fall back to Strava's GPX export.

    Returns None if the activity has neither an original file nor GPS data (e.g. manual entries).
    """
    try:
        content, fmt = _decode(session.request(f"/activities/{activity.id}/export_original").content)
    except NotFoundError:
        content, fmt = b"", None
    if fmt is None:
        if not activity.has_latlng:
            log.info("activity %s has no original file and no GPS data, skipping", activity.id)
            return None
        log.info("activity %s: original not usable, falling back to GPX export", activity.id)
        content, fmt = _decode(session.request(f"/activities/{activity.id}/export_gpx").content)
        if fmt != "gpx":
            raise StravaError(f"GPX export of activity {activity.id} returned unexpected content")
    return _atomic_write(watch_dir / f"strava-{activity.id}.{fmt}", content)


def _atomic_write(target: Path, content: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    # The temp name must not end in a supported extension so the watcher ignores it.
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target
