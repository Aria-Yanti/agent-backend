from __future__ import annotations

from collections.abc import Callable
from typing import Any


def push_event(callback: Callable[[str, dict[str, Any]], None] | None, event_name: str, payload: dict[str, Any]) -> None:
    if callback is not None:
        callback(event_name, payload)
