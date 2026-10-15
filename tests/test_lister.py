from datetime import UTC, datetime

import httpx

from strava_sync.lister import Activity, list_new_activities

from .test_session import make_jwt, me_handler
from strava_sync.session import StravaSession


def model(id_, start, latlng=True):
    return {"id": id_, "name": f"Act {id_}", "start_time": start, "sport_type": "Ride", "has_latlng": latlng}


def session_with_pages(pages, seen_pages=None):
    def extra(request):
        assert request.url.path == "/athlete/training_activities"
        page = int(request.url.params["page"])
        if seen_pages is not None:
            seen_pages.append(page)
        models = pages[page - 1] if page <= len(pages) else []
        return httpx.Response(200, json={"models": models, "page": page, "perPage": 3, "total": sum(map(len, pages))})

    s = StravaSession(make_jwt(), transport=httpx.MockTransport(me_handler(extra=extra)))
    s.login()
    return s


def test_activity_from_model_parses_dates():
    a = Activity.from_model(model(1, "2025-03-01T07:30:00+0000"))
    assert a.id == 1
    assert a.start == datetime(2025, 3, 1, 7, 30, tzinfo=UTC)
    assert a.has_latlng is True
    assert Activity.from_model({"id": 2, "start_time": "nonsense"}).start is None


def test_returns_unknown_activities_oldest_first():
    pages = [[model(3, "2025-03-03T00:00:00Z"), model(2, "2025-03-02T00:00:00Z"), model(1, "2025-03-01T00:00:00Z")]]
    result = list_new_activities(session_with_pages(pages), known_ids={2}, since=None, per_page=3)
    assert [a.id for a in result] == [1, 3]


def test_stops_at_page_with_only_known_activities():
    pages = [
        [model(6, "2025-03-06T00:00:00Z"), model(5, "2025-03-05T00:00:00Z"), model(4, "2025-03-04T00:00:00Z")],
        [model(3, "2025-03-03T00:00:00Z"), model(2, "2025-03-02T00:00:00Z"), model(1, "2025-03-01T00:00:00Z")],
        [model(0, "2025-02-01T00:00:00Z")],
    ]
    seen = []
    result = list_new_activities(session_with_pages(pages, seen), known_ids={1, 2, 3}, since=None, per_page=3)
    assert [a.id for a in result] == [4, 5, 6]
    assert seen == [1, 2]


def test_respects_since_and_stops_paging():
    pages = [
        [model(6, "2025-03-06T00:00:00Z"), model(5, "2025-03-05T00:00:00Z"), model(4, "2025-03-04T00:00:00Z")],
        [model(3, "2025-03-03T00:00:00Z"), model(2, "2025-03-02T00:00:00Z"), model(1, "2025-03-01T00:00:00Z")],
        [model(0, "2025-02-01T00:00:00Z")],
    ]
    seen = []
    since = datetime(2025, 3, 2, 12, tzinfo=UTC)
    result = list_new_activities(session_with_pages(pages, seen), known_ids=set(), since=since, per_page=3)
    assert [a.id for a in result] == [3, 4, 5, 6]
    assert seen == [1, 2]


def test_stops_at_short_page():
    pages = [[model(2, "2025-03-02T00:00:00Z"), model(1, "2025-03-01T00:00:00Z")]]
    seen = []
    result = list_new_activities(session_with_pages(pages, seen), known_ids=set(), since=None, per_page=3)
    assert [a.id for a in result] == [1, 2]
    assert seen == [1]
