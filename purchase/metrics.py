"""Served by spacey-purchase; this module calls it through `purchase/client.py`."""

from purchase import client


def compute_metrics(cur) -> dict:
    return client.compute_metrics()
