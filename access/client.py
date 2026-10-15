"""The hub's only link to the Access service (spacey-access).

Mirrors purchase/client.py: stdlib urllib, one try, a short timeout, and one
exception (AccessUnavailable) that the hub answers with 503. Each function in
access/functions.py makes exactly one call here.

The service contract is spacey-access/openapi.yaml (0.2.0). Every call carries
`Authorization: Bearer <SERVICE_TOKEN>`; spacey is the service's only caller.
"""

import json
import os
from http.client import HTTPException  # http.client's, not Werkzeug's
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import flask

from shared.logger import logger

TIMEOUT_S = 1.5


class AccessUnavailable(Exception):
    """The service gave no answer its contract allows (down, timeout, 5xx,
    token rejected, or not JSON)."""


def enabled() -> bool:
    """With ACCESS_URL set, access facts come from the service; unset (or
    empty), the hub uses its own access table, as on main. Unsetting it is
    the rollback."""
    return bool(os.getenv("ACCESS_URL"))


def call(method, path, body=None, expect=(200,)):
    """(payload, status) for an answer the contract allows; else AccessUnavailable."""
    url = os.environ["ACCESS_URL"].rstrip("/") + path
    data = None if body is None else json.dumps(body).encode()
    try:  # Request() raises ValueError on a bad URL
        request = Request(url, data, method=method, headers={
            "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}",
            "Content-Type": "application/json"})
        try:
            # One try, no retry here: the service's writes are safe to repeat,
            # so a caller may retry, but this module never hides a failure.
            with urlopen(request, timeout=TIMEOUT_S) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:  # 4xx/5xx carry the answer
            status, raw = error.code, error.read()
        if status == 401:
            raise AccessUnavailable(f"{method} {path}: SERVICE_TOKEN rejected")
        if status not in expect:
            raise AccessUnavailable(f"{method} {path}: {status}")
        return json.loads(raw), status
    except (OSError, ValueError, HTTPException) as error:
        raise AccessUnavailable(f"{method} {path}: {type(error).__name__}") from None


def init_app(app) -> None:
    """Any route whose access call fails answers 503, the same way the hub
    answers when the Purchase service is unreachable: never a 500."""

    def unavailable(error):
        # Method, path and reason only: never a body, a code or the token.
        logger.warning("access unavailable: %s %s (%s)",
                       flask.request.method, flask.request.path, error)
        return flask.jsonify(error="access unavailable"), 503

    app.register_error_handler(AccessUnavailable, unavailable)
