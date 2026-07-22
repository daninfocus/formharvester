"""Shared polling helper for asynchronous solving APIs."""

from __future__ import annotations

import time
from collections.abc import Callable


def poll_until(
    fetch: Callable[[], str | None],
    *,
    timeout: float,
    interval: float,
) -> str | None:
    """Call ``fetch`` every ``interval`` seconds until it returns a value.

    Returns the first non-empty result, or ``None`` once ``timeout`` elapses.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = fetch()
        if result:
            return result
        time.sleep(interval)
    return None
