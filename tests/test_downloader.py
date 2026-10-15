import gzip

import httpx
import pytest

from strava_sync.downloader import detect_format, download_activity
from strava_sync.lister import Activity
from strava_sync.session import StravaError, StravaSession

from .test_session import make_jwt, me_handler

FIT = b"\x0e\x10\x00\x00\x00\x00\x00\x00.FIT" + b"\x00" * 20
GPX = b'<?xml version="1.0"?>\n<gpx version="1.1"><trk/></gpx>'
TCX = b'<?xml version="1.0"?>\n<TrainingCenterDatabase></TrainingCenterDatabase>'


def activity(id_=7, latlng=True):
    return Activity(id=id_, name="x", start=None, sport_type="Ride", has_latlng=latlng)


def session_with(routes):
    calls = []

    def extra(request):
        calls.append(request.url.path)
        return routes[request.url.path]

    s = StravaSession(make_jwt(), transport=httpx.MockTransport(me_handler(extra=extra)))
    s.login()
    return s, calls


def file_response(content, filename=None, ctype="application/octet-stream"):
    headers = {"Content-Type": ctype}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return httpx.Response(200, content=content, headers=headers)


@pytest.mark.parametrize(
    "content,expected",
    [(FIT, "fit"), (GPX, "gpx"), (TCX, "tcx"), (b"  \n" + TCX, "tcx"), (b"random", None)],
)
def test_detect_format(content, expected):
    assert detect_format(content) == expected


def test_downloads_original_fit(tmp_path):
    s, calls = session_with({"/activities/7/export_original": file_response(FIT, "Morning_Ride.fit")})
    path = download_activity(s, activity(), tmp_path)
    assert path == tmp_path / "strava-7.fit"
    assert path.read_bytes() == FIT
    assert calls == ["/activities/7/export_original"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["strava-7.fit"]


def test_decompresses_gzipped_original(tmp_path):
    s, _ = session_with({"/activities/7/export_original": file_response(gzip.compress(TCX), "ride.tcx.gz")})
    path = download_activity(s, activity(), tmp_path)
    assert path == tmp_path / "strava-7.tcx"
    assert path.read_bytes() == TCX


@pytest.mark.parametrize(
    "original",
    [
        file_response(b'{"error": "no file"}', ctype="application/json"),
        httpx.Response(404),
        httpx.Response(302, headers={"Location": "https://www.strava.com/activities/7"}),
        file_response(b"unknown binary", "x.dat"),
    ],
)
def test_falls_back_to_gpx(tmp_path, original):
    s, calls = session_with(
        {"/activities/7/export_original": original, "/activities/7/export_gpx": file_response(GPX, "x.gpx")}
    )
    path = download_activity(s, activity(), tmp_path)
    assert path == tmp_path / "strava-7.gpx"
    assert calls == ["/activities/7/export_original", "/activities/7/export_gpx"]


def test_no_original_and_no_gps_returns_none(tmp_path):
    s, calls = session_with({"/activities/7/export_original": httpx.Response(404)})
    assert download_activity(s, activity(latlng=False), tmp_path) is None
    assert calls == ["/activities/7/export_original"]
    assert list(tmp_path.iterdir()) == []


def test_server_error_is_raised_not_skipped(tmp_path):
    s, _ = session_with({"/activities/7/export_original": httpx.Response(503)})
    with pytest.raises(StravaError):
        download_activity(s, activity(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_invalid_gpx_export_raises(tmp_path):
    s, _ = session_with(
        {
            "/activities/7/export_original": httpx.Response(404),
            "/activities/7/export_gpx": file_response(b"<html>", ctype="text/html"),
        }
    )
    with pytest.raises(StravaError):
        download_activity(s, activity(), tmp_path)
