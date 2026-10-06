"""JSON responses for the payment routes."""

from datetime import timezone

from flask import jsonify

_TITLES = {
    400: "Bad Request",
    402: "Payment Required",
    404: "Not Found",
}


def booking_to_json(row: dict) -> dict:
    return {
        **row,
        "start_time": row["start_time"].astimezone(timezone.utc).isoformat(),
        "end_time": row["end_time"].astimezone(timezone.utc).isoformat(),
        "created_at": row["created_at"].astimezone(timezone.utc).isoformat(),
    }


def error_body(
    status: int, detail: str, code: str, pointer: str | None = None
) -> dict:
    """4xx body. The route sets instance."""
    body = {
        "type": "about:blank",
        "title": _TITLES[status],
        "status": status,
        "detail": detail,
        "code": code,
    }
    if pointer is not None:
        body["errors"] = [{"pointer": pointer, "detail": detail}]
    return body


def json_response(payload: dict, status: int, instance: str):
    if status < 400:
        return jsonify(payload), status

    body = {
        "type": payload["type"],
        "title": payload["title"],
        "status": payload["status"],
        "detail": payload["detail"],
        "instance": instance,
        "code": payload["code"],
    }
    if "errors" in payload:
        body["errors"] = payload["errors"]
    response = jsonify(body)
    response.mimetype = "application/problem+json"
    return response, status
