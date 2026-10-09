"""JSON responses for the payment routes."""

from flask import jsonify

_TITLES = {
    400: "Bad Request",
    402: "Payment Required",
    404: "Not Found",
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
    if status < 400 or "code" not in payload:
        # success, or an unstructured error such as the 500 "payment unavailable"
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
