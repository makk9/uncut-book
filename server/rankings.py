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
from pathlib import Path

from behaviorgpt import AsyncUnboxAIClient, Order, Search, View


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
        if os.environ.get("UNBOXAI_API_KEY") and os.environ.get("UNBOXAI_CATALOG_ID"):
            self.client = AsyncUnboxAIClient(
                market="us", timezone="America/New_York",
                default_catalog_id=os.environ["UNBOXAI_CATALOG_ID"],
            )

    @staticmethod
    def _key(rows: list[dict]) -> str:
        return hashlib.sha1(json.dumps(rows, sort_keys=True).encode()).hexdigest()

    async def _rank(self, rows: list[dict]) -> tuple[list[str], str]:
        """Ids best first. Falls back to the stored snapshot if the API is unreachable."""
        key = self._key(rows)
        if key in self.cache:
            return self.cache[key], "cache"
        if self.client is not None:
            try:
                async with self.sem:
                    res = await self.client.complete(
                        to_events(rows), limit=100, filters={"id": self.ids}, register_event=False
                    )
                order = [i.id for i in res.items]
                self.cache[key] = order
                self._persist(key, order)
                return order, "live"
            except Exception as exc:  # the demo must survive a network failure
                print("ranking failed, using snapshot:", type(exc).__name__, str(exc)[:160], flush=True)
        if key in self.snapshot:
            return self.snapshot[key], "snapshot"
        return [], "missing"

    def _persist(self, key: str, order: list[str]) -> None:
        """Keep every real ranking on disk, so an outage replays real output instead of failing."""
        self.snapshot[key] = order
        try:
            self.snapshot_path.write_text(json.dumps(self.snapshot))
        except OSError:
            pass  # a read-only host still has the snapshot it shipped with

    async def collector(self, events: list[dict], signals: list[dict]) -> dict:
        full_rows = events + signals
        order_rows = [e for e in events if e["type"] == "order"]
        (full, s1), (orders, s2) = await asyncio.gather(self._rank(full_rows), self._rank(order_rows))
        return {"full": full, "orders": orders, "source": "live" if "live" in (s1, s2) else s1}

    async def wider(self, rows: list[dict], exclude: set[str], limit: int = 12) -> list[str]:
        """What they would look at next across the whole catalog, for sourcing."""
        if self.client is None:
            return []
        res = await self.client.complete(to_events(rows), limit=min(100, limit + len(exclude)),
                                         register_event=False)
        return [i.id for i in res.items if i.id not in exclude][:limit]

