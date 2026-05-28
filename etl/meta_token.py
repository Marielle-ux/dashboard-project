"""
Meta (Facebook) access-token lifecycle helper.

Provides :func:`get_access_token` which returns a valid, non-expired access
token for the Meta Marketing API. On first use the configured token is
inspected via the ``debug_token`` endpoint and, if it expires within
``REFRESH_THRESHOLD_SECONDS``, automatically exchanged for a fresh long-lived
token using ``fb_exchange_token`` (requires ``META_APP_ID`` and
``META_APP_SECRET``).

The refreshed token is cached in-process. On Streamlit Cloud each cold start
re-runs the check, so the secrets stored in the deployment do not need to be
manually rotated as long as the app is started at least once before the
configured token expires.

If refresh is impossible (no app credentials, network error, expired token)
the configured token is returned unchanged so the rest of the app keeps
working and the existing error reporting surfaces the underlying issue.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import requests

from config import settings

logger = logging.getLogger(__name__)

# Refresh tokens that expire within this window (default: 7 days).
REFRESH_THRESHOLD_SECONDS = 7 * 24 * 3600

# Re-check expiry every this often (default: 1 hour) even if we already have
# a token cached. Cheap (one HTTP call) and avoids using a stale cached
# expiry for very long-running processes.
RECHECK_INTERVAL_SECONDS = 3600


@dataclass
class TokenInfo:
    """Non-sensitive snapshot of the current token state for the debug panel."""

    token_present: bool
    expires_at: Optional[int]  # unix ts (seconds), or None if unknown
    refreshed: bool             # True if this process minted a new token
    last_check: Optional[float]
    error: Optional[str]


_cache_lock = threading.Lock()
_cache: dict = {
    "token": "",
    "expires_at": None,        # type: Optional[int]
    "refreshed": False,
    "last_check": None,        # type: Optional[float]
    "error": None,             # type: Optional[str]
}


def _api_base() -> str:
    return f"https://graph.facebook.com/{settings.meta_ads.api_version}"


def _probe_expiry(token: str) -> tuple[Optional[int], Optional[str]]:
    """Return ``(expires_at_unix, error)`` for *token* via debug_token.

    ``expires_at`` is ``None`` and ``error`` describes the failure when the
    Graph API call cannot be made or the token is invalid. ``expires_at`` is
    ``0`` for tokens that never expire (e.g. system-user tokens).
    """
    cfg = settings.meta_ads
    if not cfg.app_id or not cfg.app_secret:
        # debug_token requires an app token to inspect a user token.
        return None, "META_APP_ID and META_APP_SECRET required to inspect token"
    app_token = f"{cfg.app_id}|{cfg.app_secret}"
    try:
        r = requests.get(
            f"https://graph.facebook.com/debug_token",
            params={"input_token": token, "access_token": app_token},
            timeout=15,
        )
        body = r.json()
    except requests.RequestException as exc:
        return None, f"debug_token network error: {exc}"
    except ValueError:
        return None, "debug_token returned non-JSON response"

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None, f"debug_token: unexpected response shape ({body!r})"
    if data.get("is_valid") is False:
        err = data.get("error", {}) or {}
        return None, f"token invalid: {err.get('message', 'unknown reason')}"
    # `expires_at` is unix seconds, or 0 if the token never expires.
    exp = data.get("expires_at")
    if isinstance(exp, int):
        return exp, None
    return None, f"debug_token: no expires_at in response ({data!r})"


def _exchange_for_long_lived(token: str) -> tuple[Optional[str], Optional[str]]:
    """Return ``(new_token, error)`` from fb_exchange_token.

    Returns ``(None, error)`` if exchange is unsupported (missing app creds),
    the network call fails, or Graph returns an error payload.
    """
    cfg = settings.meta_ads
    if not cfg.app_id or not cfg.app_secret:
        return None, "META_APP_ID and META_APP_SECRET required to refresh token"
    try:
        r = requests.get(
            f"{_api_base()}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": cfg.app_id,
                "client_secret": cfg.app_secret,
                "fb_exchange_token": token,
            },
            timeout=20,
        )
        body = r.json()
    except requests.RequestException as exc:
        return None, f"fb_exchange_token network error: {exc}"
    except ValueError:
        return None, "fb_exchange_token returned non-JSON response"

    if not isinstance(body, dict):
        return None, f"fb_exchange_token: unexpected response ({body!r})"
    if "error" in body:
        err = body["error"]
        return None, f"fb_exchange_token: {err.get('message', err)}"
    new_token = body.get("access_token")
    if isinstance(new_token, str) and new_token:
        return new_token, None
    return None, f"fb_exchange_token: no access_token in response ({body!r})"


def _is_near_expiry(expires_at: Optional[int]) -> bool:
    """True if the token expires within REFRESH_THRESHOLD_SECONDS.

    ``expires_at == 0`` means the token never expires — return False.
    ``expires_at is None`` means we couldn't determine expiry — return False
    (we don't want to spam exchange attempts when probing failed).
    """
    if expires_at is None:
        return False
    if expires_at == 0:
        return False
    return (expires_at - time.time()) < REFRESH_THRESHOLD_SECONDS


def _refresh_if_needed() -> None:
    """Inspect the configured token and refresh it in-place if near expiry.

    Idempotent: subsequent calls within ``RECHECK_INTERVAL_SECONDS`` are
    no-ops. Safe to call concurrently from multiple threads.
    """
    cfg = settings.meta_ads
    original = cfg.access_token or ""

    with _cache_lock:
        now = time.time()
        last_check = _cache["last_check"]
        cached_token = _cache["token"]

        # If we recently checked and have a non-empty cached token, reuse it.
        if (
            cached_token
            and last_check is not None
            and (now - last_check) < RECHECK_INTERVAL_SECONDS
        ):
            return

        if not original:
            _cache["token"] = ""
            _cache["expires_at"] = None
            _cache["refreshed"] = False
            _cache["last_check"] = now
            _cache["error"] = "META_ACCESS_TOKEN is not set"
            return

        expiry, err = _probe_expiry(original)
        if err is not None:
            # Couldn't probe — keep the original token, surface the error.
            _cache["token"] = original
            _cache["expires_at"] = expiry
            _cache["refreshed"] = False
            _cache["last_check"] = now
            _cache["error"] = err
            logger.warning("Meta token expiry check failed: %s", err)
            return

        token = original
        refreshed = False
        if _is_near_expiry(expiry):
            new_token, exc_err = _exchange_for_long_lived(original)
            if new_token:
                token = new_token
                refreshed = True
                new_expiry, _ = _probe_expiry(new_token)
                expiry = new_expiry if new_expiry is not None else expiry
                logger.info(
                    "Meta access token refreshed; new expiry=%s", expiry
                )
            else:
                logger.warning(
                    "Meta access token near expiry but refresh failed: %s",
                    exc_err,
                )
                _cache["error"] = exc_err
                expiry = expiry  # keep what we had

        _cache["token"] = token
        _cache["expires_at"] = expiry
        _cache["refreshed"] = refreshed
        _cache["last_check"] = now
        if not refreshed and not _cache.get("error"):
            _cache["error"] = None


def get_access_token() -> str:
    """Return a usable Meta access token, auto-refreshing when near expiry.

    Falls back to the configured token verbatim when refresh is not possible
    (missing app credentials, network error, etc.).
    """
    _refresh_if_needed()
    return _cache.get("token") or settings.meta_ads.access_token or ""


def token_info() -> TokenInfo:
    """Return a non-sensitive snapshot of the cached token state.

    Triggers a check if the cache is empty. Used by the debug panel.
    """
    if _cache.get("last_check") is None:
        _refresh_if_needed()
    return TokenInfo(
        token_present=bool(_cache.get("token")),
        expires_at=_cache.get("expires_at"),
        refreshed=bool(_cache.get("refreshed")),
        last_check=_cache.get("last_check"),
        error=_cache.get("error"),
    )


def reset_cache() -> None:
    """Clear the in-process cache. Intended for tests and manual reruns."""
    with _cache_lock:
        _cache["token"] = ""
        _cache["expires_at"] = None
        _cache["refreshed"] = False
        _cache["last_check"] = None
        _cache["error"] = None
