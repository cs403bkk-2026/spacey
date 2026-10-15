"""Served by spacey-purchase; this module calls it through `purchase/client.py`."""

from purchase import client, mirror


def register_user(cur, email, password):
    """Create an account, storing only a hash of the password.
    Returns (payload, status) - {"id": ..., "email": ...}, or an error."""
    payload, status = client.register_user(email, password)
    if status == 201:
        mirror.user(payload, password)
    return payload, status


def authenticate(cur, email, password):
    """Check an email and password; the caller starts the session.
    Returns (payload, status) - {"id": ..., "email": ...}, or an error.
    Wrong password and unknown email give the identical error, so a
    failed attempt can't be used to find out which emails are registered."""
    return client.authenticate(email, password)


def subscribe(cur, name):
    """Subscriptions are removed: always 410, touches no data, so an old
    client gets a readable error instead of a 404."""
    return {"error": "subscriptions have been removed"}, 410
