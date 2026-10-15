"""Authenticated Strava web session based on the `strava_remember_token` browser cookie."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

BASE_URL = "https://www.strava.com"
COOKIE_DOMAIN = ".strava.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class StravaError(Exception):
    pass


class AuthExpiredError(StravaError):
    pass


class RateLimitError(StravaError):
    pass


class NotFoundError(StravaError):
    pass


def parse_remember_token(token: str) -> tuple[str, int]:
    """Return (athlete web id, expiry unix timestamp) from the JWT payload (signature is not verified)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return str(data["sub"]), int(data["exp"])
    except (IndexError, ValueError, KeyError, TypeError) as exc:
        raise AuthExpiredError(f"strava_remember_token is malformed: {exc}") from None


class StravaSession:
    def __init__(self, remember_token: str, transport: httpx.BaseTransport | None = None, timeout: float = 60):
        self._token = remember_token
        self.athlete_id, self._expires = parse_remember_token(remember_token)
        self._client = httpx.Client(
            base_url=BASE_URL,
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        )
        self._client.cookies.set("strava_remember_id", self.athlete_id, domain=COOKIE_DOMAIN)
        self._client.cookies.set("strava_remember_token", remember_token, domain=COOKIE_DOMAIN)

    @property
    def remember_token(self) -> str:
        """Latest remember token; Strava may rotate it via Set-Cookie."""
        for cookie in self._client.cookies.jar:
            if cookie.name == "strava_remember_token" and cookie.value:
                return cookie.value
        return self._token

    def login(self) -> None:
        if self._expires <= time.time():
            raise AuthExpiredError("strava_remember_token has expired, copy a fresh one from the browser")
        response = self._client.get("/me")
        if response.status_code == 429:
            raise RateLimitError("rate limited by Strava on /me")
        if response.status_code >= 500:
            raise StravaError(f"/me returned HTTP {response.status_code}")
        location = response.headers.get("Location", "")
        if not (response.is_redirect and location.rstrip("/").endswith(f"/{self.athlete_id}")):
            raise AuthExpiredError(
                f"login with strava_remember_token failed (HTTP {response.status_code}, Location={location!r})"
            )

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.request(
            path,
            params=params,
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )
        try:
            return response.json()
        except ValueError:
            raise AuthExpiredError(f"{path} returned non-JSON content, session is probably invalid") from None

    def request(self, path: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        response = self._client.get(path, params=params, headers=headers)
        if response.status_code == 429:
            raise RateLimitError(f"rate limited by Strava on {path}")
        if response.status_code in (401, 403):
            raise AuthExpiredError(f"{path} returned HTTP {response.status_code}")
        if response.is_redirect:
            location = response.headers.get("Location", "")
            if "/login" in location or "/session" in location:
                raise AuthExpiredError(f"{path} redirected to login")
            raise NotFoundError(f"{path} redirected to {location!r}")
        if response.status_code == 404:
            raise NotFoundError(f"{path} returned HTTP 404")
        if response.status_code != 200:
            raise StravaError(f"{path} returned HTTP {response.status_code}")
        return response

    def close(self) -> None:
        self._client.close()
