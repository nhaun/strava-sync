import base64
import json
import time

import httpx
import pytest

from strava_sync.session import (
    AuthExpiredError,
    RateLimitError,
    StravaError,
    StravaSession,
    parse_remember_token,
)


def make_jwt(sub=12345, exp=None):
    exp = exp if exp is not None else int(time.time()) + 3600
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub, "exp": exp}).encode()).rstrip(b"=")
    return f"eyJhbGciOiJIUzI1NiJ9.{payload.decode()}.sig"


def test_parse_remember_token():
    web_id, exp = parse_remember_token(make_jwt(sub=42, exp=2_000_000_000))
    assert web_id == "42"
    assert exp == 2_000_000_000


@pytest.mark.parametrize("token", ["garbage", "a.b.c", "a." + base64.b64encode(b"[]").decode() + ".c"])
def test_parse_remember_token_malformed(token):
    with pytest.raises(AuthExpiredError, match="malformed"):
        parse_remember_token(token)


def test_expired_token_rejected_before_any_request():
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))
    with pytest.raises(AuthExpiredError, match="expired"):
        StravaSession(make_jwt(exp=int(time.time()) - 10), transport=transport).login()
    assert calls == []


def me_handler(web_id="12345", extra=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/me":
            assert f"strava_remember_token=" in request.headers["cookie"]
            assert f"strava_remember_id={web_id}" in request.headers["cookie"]
            return httpx.Response(
                302,
                headers={"Location": f"https://www.strava.com/athletes/{web_id}"},
            )
        return extra(request)

    return handler


def test_login_success():
    session = StravaSession(make_jwt(), transport=httpx.MockTransport(me_handler()))
    session.login()
    assert session.athlete_id == "12345"


def test_login_redirect_to_login_page_fails():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"Location": "https://www.strava.com/login"})
    )
    with pytest.raises(AuthExpiredError):
        StravaSession(make_jwt(), transport=transport).login()


def test_get_json_sends_xhr_headers():
    def extra(request):
        assert request.headers["X-Requested-With"] == "XMLHttpRequest"
        assert "Mozilla" in request.headers["User-Agent"]
        assert request.url.params["page"] == "2"
        return httpx.Response(200, json={"models": []})

    session = StravaSession(make_jwt(), transport=httpx.MockTransport(me_handler(extra=extra)))
    session.login()
    assert session.get_json("/athlete/training_activities", params={"page": 2}) == {"models": []}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>login</html>", headers={"Content-Type": "text/html"}),
        httpx.Response(302, headers={"Location": "https://www.strava.com/login"}),
        httpx.Response(401),
    ],
)
def test_get_json_auth_failures(response):
    session = StravaSession(make_jwt(), transport=httpx.MockTransport(me_handler(extra=lambda r: response)))
    session.login()
    with pytest.raises(AuthExpiredError):
        session.get_json("/athlete/training_activities")


def test_rate_limit():
    session = StravaSession(
        make_jwt(), transport=httpx.MockTransport(me_handler(extra=lambda r: httpx.Response(429)))
    )
    session.login()
    with pytest.raises(RateLimitError):
        session.get_json("/x")


def test_server_error():
    session = StravaSession(
        make_jwt(), transport=httpx.MockTransport(me_handler(extra=lambda r: httpx.Response(503)))
    )
    session.login()
    with pytest.raises(StravaError, match="503"):
        session.get_json("/x")


def test_rotated_remember_token_is_exposed():
    new_token = make_jwt(exp=int(time.time()) + 999_999)

    def handler(request):
        return httpx.Response(
            302,
            headers=[
                ("Location", "https://www.strava.com/athletes/12345"),
                ("Set-Cookie", f"strava_remember_token={new_token}; Domain=.strava.com; Path=/; Secure"),
            ],
        )

    session = StravaSession(make_jwt(), transport=httpx.MockTransport(handler))
    session.login()
    assert session.remember_token == new_token
