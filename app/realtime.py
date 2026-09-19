from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RealtimeEvent:
    seq: int
    campaign_id: int | None
    kind: str
    path: str
    payload: dict[str, Any]
    created_at: float


class EventBus:
    """Tiny in-process event journal used by Seeker's SSE endpoint.

    Seeker is normally deployed as one Railway web process, so an in-process
    journal avoids a Redis dependency while replacing the many browser polling
    loops with one authenticated stream. The browser retains low-frequency
    fallbacks for multi-worker or temporarily disconnected deployments.
    """

    def __init__(self, max_events: int = 512) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._events: deque[RealtimeEvent] = deque(maxlen=max_events)

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._seq

    def publish(self, kind: str, *, path: str = "", campaign_id: int | None = None, payload: dict[str, Any] | None = None) -> RealtimeEvent:
        with self._lock:
            self._seq += 1
            event = RealtimeEvent(
                seq=self._seq,
                campaign_id=int(campaign_id) if campaign_id is not None else None,
                kind=str(kind or "state.changed")[:120],
                path=str(path or "")[:500],
                payload=dict(payload or {}),
                created_at=time.time(),
            )
            self._events.append(event)
            return event

    def after(self, sequence: int, *, campaign_id: int | None = None) -> list[RealtimeEvent]:
        with self._lock:
            rows = [event for event in self._events if event.seq > int(sequence or 0)]
        if campaign_id is None:
            return rows
        cid = int(campaign_id)
        return [event for event in rows if event.campaign_id in {None, cid}]

    @staticmethod
    def sse(event: RealtimeEvent) -> str:
        body = {
            "seq": event.seq,
            "kind": event.kind,
            "path": event.path,
            "campaign_id": event.campaign_id,
            "created_at": event.created_at,
            **event.payload,
        }
        return f"id: {event.seq}\nevent: seeker\ndata: {json.dumps(body, separators=(',', ':'), ensure_ascii=False)}\n\n"


BUS = EventBus()
