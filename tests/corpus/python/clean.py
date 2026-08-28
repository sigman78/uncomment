#!/usr/bin/env python
"""Retry helpers shared by the sync clients.

The registry drops the first request under load, so every public call
retries once with a short backoff.
"""

from __future__ import annotations

import time

_BACKOFF_SECONDS = 0.05  # tuned against the staging registry
_seen: dict = {}  # (src, dst) -> first "file:line" seen
_glyphs: dict = {}  # WxH: (normal BDF, bold BDF)
_last_write = None  # None = never written (a bug)

# Cyrillic (basic Russian + extensions)
CYRILLIC_RANGE = (0x0400, 0x04FF)


def fetch(client, key):
    """Return the raw record for key.

    Args:
        client: transport with a get() method.
        key: registry key, always lowercase.

    Raises:
        LookupError: when the registry has no record for key.
    """
    try:
        return client.get(key)
    except TimeoutError:
        # workaround: the registry drops the first request under load
        time.sleep(_BACKOFF_SECONDS)
        return client.get(key)


class Cache:
    """Small LRU that keeps registry lookups off the hot path."""

    def __init__(self, size: int = 128):
        self.size = size
        self.entries: dict[str, object] = {}

    def put(self, key: str, value: object) -> None:  # noqa: D102
        if len(self.entries) >= self.size:
            self.entries.pop(next(iter(self.entries)))
        self.entries[key] = value
