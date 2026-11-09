"""BehaviorGPT rankings of the batch, per collector, through two lenses.

full   : everything the collector did, in order, plus any signal logged today.
orders : only what they bought. BehaviorGPT weighs recent events heavily, so one
         stray view can reorder a list. This lens anchors long-term taste, and the
         gap between the two is the taste-drift signal shown in the UI.

Raw scores are never used in money math. They sit in a narrow band and are not
probabilities, so everything downstream uses rank within the batch.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import deque
from pathlib import Path

from behaviorgpt import AsyncUnboxAIClient, Order, Search, View

MAX_STORED = 2000  # rankings kept in memory and on disk, so a public URL can't grow them forever
WORST_FIRST = ("limited", "missing", "snapshot", "live", "cache")


class Spend:
    """Sliding-window cap. Anyone with the URL spends live calls on the server's API key."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self.times: deque[float] = deque()

    def take(self, n: int = 1) -> bool:
        now = time.monotonic()
        while self.times and now - self.times[0] > self.window:
            self.times.popleft()
        if len(self.times) + n > self.limit:
            return False
        self.times.extend([now] * n)
        return True


def to_events(rows: list[dict]) -> list:
    out = []
    for e in rows:
        if e["type"] == "search":
            out.append(Search(e["q"]))
        elif e["type"] == "view":
            out.append(View(e["id"]))
        elif e["type"] == "order":
            out.append(Order([e["id"]]))
    return out


class Ranker:
    def __init__(self, ids: list[str], snapshot_path: Path):
        self.ids = ids
        self.snapshot_path = snapshot_path
        self.snapshot = json.loads(snapshot_path.read_text()) if snapshot_path.exists() else {}
        self.cache: dict[str, list[str]] = {}
        self.sem = asyncio.Semaphore(8)
        self.client = None
        self.source = "snapshot"
        self.spend = Spend(int(os.environ.get("LIVE_CALLS_PER_HOUR", "1000")), 3600)
        if os.environ.get("UNBOXAI_API_KEY") and os.environ.get("UNBOXAI_CATALOG_ID"):
            self.client = AsyncUnboxAIClient(
                market="us", timezone="America/New_York",
                default_catalog_id=os.environ["UNBOXAI_CATALOG_ID"],
            )

    @staticmethod
    def _key(rows: list[dict]) -> str:
        return hashlib.sha1(json.dumps(rows, sort_keys=True).encode()).hexdigest()

    def is_new(self, rows: list[dict]) -> bool:
        """Would ranking these events spend a live call?"""
        return self.client is not None and self._key(rows) not in self.cache

    async def _rank(self, rows: list[dict]) -> tuple[list[str], str]:
        """Ids best first. Falls back to the stored snapshot if the API is unreachable or the cap is reached."""
        key = self._key(rows)
        if key in self.cache:
            return self.cache[key], "cache"
        limited = False
        if self.client is not None:
            limited = not self.spend.take()
            if not limited:
                try:
                    async with self.sem:
                        res = await self.client.complete(
                            to_events(rows), limit=100, filters={"id": self.ids}, register_event=False
                        )
                    order = [i.id for i in res.items]
                    while len(self.cache) >= MAX_STORED:
                        self.cache.pop(next(iter(self.cache)))
                    self.cache[key] = order
                    self._persist(key, order)
                    return order, "live"
                except Exception as exc:  # the demo must survive a network failure
                    print("ranking failed, using snapshot:", type(exc).__name__, str(exc)[:160], flush=True)
        if key in self.snapshot:
            return self.snapshot[key], "snapshot"
        return [], "limited" if limited else "missing"

    def _persist(self, key: str, order: list[str]) -> None:
        """Keep real rankings on disk, so an outage replays real output instead of failing."""
        if len(self.snapshot) >= MAX_STORED:
            return
        self.snapshot[key] = order
        try:
            self.snapshot_path.write_text(json.dumps(self.snapshot))
        except OSError:
            pass  # a read-only host still has the snapshot it shipped with

    async def collector(self, events: list[dict], signals: list[dict]) -> dict:
        full_rows = events + signals
        order_rows = [e for e in events if e["type"] == "order"]
        (full, s1), (orders, s2) = await asyncio.gather(self._rank(full_rows), self._rank(order_rows))
        # report the weakest of the two lenses, so an outage or a cap is never shown as live
        return {"full": full, "orders": orders, "source": next(s for s in WORST_FIRST if s in (s1, s2))}

