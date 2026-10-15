"""Served by spacey-purchase; this module calls it through `purchase/client.py`."""

from purchase import client, mirror


def booked_space_ids(cur, window) -> set:
    """Spaces booked during the window, or booked right now if no window."""
    return client.booked_space_ids(window)


def list_spaces(cur) -> list:
    return client.list_spaces()


def get_space(cur, space_id) -> dict | None:
    return client.get_space(space_id)


def create_space(cur, name, capacity, price_cents):
    """Add a space after checking its fields; the name is stored trimmed.
    Returns (payload, status) - the new space, or an {"error": ...}."""
    payload, status = client.create_space(name, capacity, price_cents)
    if status == 201:
        mirror.space(payload)
    return payload, status


def update_space(cur, space_id, fields):
    """Change a space's name, capacity and/or price. fields is the request
    body: a field left out keeps its current value, but one sent as null is
    rejected - so this needs the body itself, not just its values.
    Returns (payload, status) - the updated space, or an {"error": ...}."""
    payload, status = client.update_space(space_id, fields)
    if status == 200:
        mirror.space(payload)
    return payload, status


def delete_space(cur, space_id):
    """Delete a space, refused while it still has bookings.
    Returns (payload, status) - payload is None once deleted."""
    payload, status = client.delete_space(space_id)
    if status == 204:
        mirror.delete_space(space_id)
    return payload, status
