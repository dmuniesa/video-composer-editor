"""In-process SSE broadcaster. Each browser tab subscribes to a project's
event stream; jobs and the MCP notify endpoint publish typed events that
tell the UI which slice of state to refetch."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any


class Broadcaster:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, pid: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers[pid].add(q)
        return q

    def unsubscribe(self, pid: str, q: asyncio.Queue) -> None:
        self._subscribers[pid].discard(q)

    def publish(self, pid: str, event: str, data: dict[str, Any] | None = None) -> None:
        """Thread-safe publish; callable from worker threads."""
        payload = {"event": event, "data": data or {}}
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._publish_now, pid, payload)

    def _publish_now(self, pid: str, payload: dict) -> None:
        for q in list(self._subscribers.get(pid, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass


broadcaster = Broadcaster()


def sse_format(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
