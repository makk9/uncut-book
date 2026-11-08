"""THE BOOK API: rank the batch per collector, then solve the acquisition."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server import optimizer as opt
from server.rankings import Ranker

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
BOOK = ROOT / "data" / "book"
PIECES = {p["id"]: p for p in json.loads((BOOK / "pieces.json").read_text())}
COLLECTORS = json.loads((BOOK / "collectors.json").read_text())
BY_ID = {c["id"]: c for c in COLLECTORS}
LOTS = [p for p in PIECES.values() if p["role"] == "lot"]
HOLDINGS = [p for p in PIECES.values() if p["role"] == "holding"]
LOT_IDS = [p["id"] for p in LOTS]
HOLD_IDS = [p["id"] for p in HOLDINGS]
ALL_IDS = LOT_IDS + HOLD_IDS
# Who has already looked at each held piece. Having viewed a piece lifts its rank for that collector,
# so the UI shows this next to the rank instead of passing it off as independent demand.
VIEWED_BY = {i: [c["id"] for c in COLLECTORS if any(e["type"] == "view" and e["id"] == i for e in c["events"])]
             for i in HOLD_IDS}

ranker = Ranker(ALL_IDS, BOOK / "rankings_snapshot.json")
app = FastAPI(title="THE BOOK")


class Signal(BaseModel):
    type: str = Field(pattern="^(search|view)$")
    q: str | None = Field(default=None, max_length=120)
    id: str | None = Field(default=None, max_length=64)


class Request(BaseModel):
    budget: float = Field(default=80_000, ge=0, le=1_000_000)  # capital still available, not a target
    fit_decay: float = Field(default=4.0, ge=0.5, le=20)
    holding_penalty: float = Field(default=0.15, ge=0, le=1)
    max_rank: int = Field(default=8, ge=1, le=24)
    slots: int = Field(default=2, ge=1, le=6)
    capacity_tolerance: float = Field(default=0.25, ge=0, le=1)
    stretch_cost: float = Field(default=0.50, ge=0, le=5)
    recency: float = Field(default=0.6, ge=0, le=1)
    relative: float = Field(default=1.0, ge=0, le=3)
    signals: dict[str, list[Signal]] = Field(default_factory=dict)
    passes: list[tuple[str, str]] = Field(default_factory=list)
    radar: list[str] | None = None  # lots visible to the dealer; None means all of them
    plan: list[str] = Field(default_factory=list)  # what the dealer intends to buy; the suggestion works around it
    prefer: dict[str, str] = Field(default_factory=dict)  # lot -> buyer the dealer was shown; only ever breaks exact ties


def purchases(c: dict) -> dict:
    """What the history actually shows this collector paying. A fact from their record, not a prediction."""
    paid = sorted(PIECES[e["id"]]["resale"] for e in c["events"] if e["type"] == "order")
    if not paid:
        return {"count": 0, "low": None, "typical": None, "high": None}
    return {"count": len(paid), "low": paid[0], "typical": paid[len(paid) // 2], "high": paid[-1]}


def tag_set(p: dict) -> set[str]:
    return {f"form:{p['form']}", f"era:{p['era']}", f"style:{p['style']}",
            *[f"stone:{s}" for s in p["stones"]], *[f"metal:{m}" for m in p["metals"]]}


def tag_rank(events: list[dict], ids: list[str]) -> list[str]:
    """The deterministic baseline: count overlaps with tags of what they viewed and bought."""
    profile: dict[str, float] = {}
    for e in events:
        if e["type"] in ("view", "order") and e["id"] in PIECES:
            for t in tag_set(PIECES[e["id"]]):
                profile[t] = profile.get(t, 0) + (3 if e["type"] == "order" else 1)
    return sorted(ids, key=lambda i: -sum(profile.get(t, 0) for t in tag_set(PIECES[i])))


def within(order: list[str], ids: list[str]) -> dict[str, int]:
    """1-based rank of each id among `ids`, keeping the given order."""
    wanted = set(ids)
    sub = [i for i in order if i in wanted]
    ranks = {i: n + 1 for n, i in enumerate(sub)}
    for i in ids:  # anything the API left out goes last
        ranks.setdefault(i, len(ids))
    return ranks


def relative_ranks(position: dict[str, dict[str, float]], relative: float, ids: list[str]) -> dict[str, dict[str, int]]:
    """Rank each collector's lots by own position plus how far above the book average it is.

    Some lots rank well for almost everyone, so raw rank piles the whole book onto them.
    Only real BehaviorGPT ranks go in, and no scores or probabilities are involved.
    """
    book = {i: sum(p[i] for p in position.values()) / len(position) for i in ids}
    return {
        cid: {i: n + 1 for n, i in enumerate(sorted(ids, key=lambda i: (p[i] - relative * (book[i] - p[i]), p[i])))}
        for cid, p in position.items()
    }


async def gather_rankings(req: Request) -> dict:
    for cid, sig in req.signals.items():
        if cid not in BY_ID or len(sig) > 12:
            raise HTTPException(422, "unknown collector or too many signals")
        for s in sig:
            if s.type == "view" and s.id not in PIECES:
                raise HTTPException(422, "unknown piece")
            if s.type == "search" and not (s.q or "").strip():
                raise HTTPException(422, "empty search")
    results = await asyncio.gather(*(
        ranker.collector(c["events"], [s.model_dump(exclude_none=True) for s in req.signals.get(c["id"], [])])
        for c in COLLECTORS
    ))
    return {c["id"]: r for c, r in zip(COLLECTORS, results)}


@app.get("/api/book")
def book():
    def public(p):
        return {k: v for k, v in p.items() if k != "embed_name"}

    collectors = [{k: v for k, v in c.items() if k != "events"} | {
        "timeline": [
            {**e, "name": PIECES[e["id"]]["name"], "image": PIECES[e["id"]]["image"]} if "id" in e else e
            for e in c["events"][-14:]
        ],
        "event_count": len(c["events"]),
        "purchases": purchases(c),
    } for c in COLLECTORS]
    return {
        "lots": [public(p) for p in LOTS],
        "holdings": [public(p) for p in HOLDINGS],
        "collectors": collectors,
        "live": ranker.client is not None,
    }


async def build(req: Request):
    """Rankings for this request, in the shape the solver takes."""
    started = time.perf_counter()
    raw = await gather_rankings(req)
    rank_ms = (time.perf_counter() - started) * 1000
    sources = {r["source"] for r in raw.values()}
    if "missing" in sources:
        raise HTTPException(503, "BehaviorGPT is unreachable and this signal has no stored ranking.")

    known = set(LOT_IDS)
    named = (req.radar or []) + req.plan
    if any(l not in known for l in named):
        raise HTTPException(422, "unknown lot")
    # ranks are taken among the lots the dealer can see, so "#3 of 20" stays true as offers come and go
    pool = LOT_IDS if req.radar is None else req.radar

    lens, tags = {}, {}
    for c in COLLECTORS:
        cid = c["id"]
        full = within(raw[cid]["full"], pool)
        orders = within(raw[cid]["orders"], pool)
        lens[cid] = {"full": full, "orders": orders}
        tags[cid] = within(tag_rank(c["events"], pool), pool)
    position = {cid: {l: req.recency * v["full"][l] + (1 - req.recency) * v["orders"][l] for l in pool}
                for cid, v in lens.items()}
    for cid, order in relative_ranks(position, req.relative, pool).items():
        lens[cid]["blend"] = order

    shape = (len(pool), len(COLLECTORS))
    ranks = np.array([[lens[c["id"]]["blend"][l] for c in COLLECTORS] for l in pool], float).reshape(shape)
    tag_ranks = np.array([[tags[c["id"]][l] for c in COLLECTORS] for l in pool], float).reshape(shape)
    lots = [{"id": l, "ask": PIECES[l]["ask"], "resale": PIECES[l]["resale"]} for l in pool]
    buyers = [{"id": c["id"], "capacity": c["capacity"], "slots": req.slots} for c in COLLECTORS]
    blocked = {tuple(x) for x in req.passes}
    problem = opt.Problem(lots, buyers, ranks, blocked)
    q = opt.Params(budget=req.budget, fit_decay=req.fit_decay, holding_penalty=req.holding_penalty,
                   max_rank=req.max_rank, slots=req.slots,
                   capacity_tolerance=req.capacity_tolerance, stretch_cost=req.stretch_cost)
    return raw, sources, rank_ms, lens, tags, ranks, tag_ranks, lots, buyers, blocked, pool, problem, q


FRONTIER_CACHE: dict[bytes, list] = {}


def cached_frontier(problem, q, blocked) -> list[dict]:
    """The curve does not depend on the budget being looked at, so a slider drag reuses it."""
    key = (problem.ranks.tobytes() + repr((q.fit_decay, q.holding_penalty, q.max_rank, q.slots, q.capacity_tolerance, q.stretch_cost,
                                           sorted(blocked), [l["id"] for l in problem.lots],
                                           [(c["capacity"], c.get("slots")) for c in problem.collectors])).encode())
    if key not in FRONTIER_CACHE:
        if len(FRONTIER_CACHE) > 256:
            FRONTIER_CACHE.clear()
        FRONTIER_CACHE[key] = opt.frontier(problem, q, list(range(10_000, 200_001, 10_000)))
    return FRONTIER_CACHE[key]


def plan_and_next(problem: opt.Problem, q: opt.Params, plan: list[str], suggested: dict, prefer: dict[str, str]) -> tuple[dict, dict]:
    """Score what the dealer plans to buy by the solver's own rules, then ask the solver what it
    would add with the capital left. Planned pieces use up their buyer's capacity and slots."""
    at = {l["id"]: i for i, l in enumerate(problem.lots)}
    chosen = [at[l] for l in dict.fromkeys(plan) if l in at]
    mine = opt.keep_buyers(problem, q, opt.evaluate(problem, q, chosen), prefer)
    mine["ties"] = opt.buyer_ties(problem, q, mine)
    if not chosen:
        return mine, suggested
    buyers = []
    for c in problem.collectors:
        held = [x for x in mine["picks"] if x["buyer"] == c["id"]]
        buyers.append({"id": c["id"], "capacity": max(0.0, c["capacity"] - sum(x["resale"] for x in held)),
                       "slots": max(0, c["slots"] - len(held))})
    rest = [i for i in range(len(problem.lots)) if i not in set(chosen)]
    remaining = opt.Problem([problem.lots[i] for i in rest], buyers, problem.ranks[np.array(rest, dtype=int)], problem.blocked)
    q_left = replace(q, budget=max(0.0, q.budget - mine["spent"]))
    nxt = opt.solve(remaining, q_left)
    nxt["ties"] = opt.buyer_ties(remaining, q_left, nxt)
    return mine, nxt


@app.post("/api/portfolio")
async def portfolio(req: Request):
    raw, sources, rank_ms, lens, tags, ranks, tag_ranks, lots, buyers, blocked, pool, problem, q = await build(req)

    t1 = time.perf_counter()
    base = opt.solve(problem, q)
    base["ties"] = opt.buyer_ties(problem, q, base)
    chosen = opt.lots_for(problem, base)
    mine, nxt = plan_and_next(problem, q, req.plan, base, req.prefer)
    solve_ms = (time.perf_counter() - t1) * 1000

    # the same budget and scoring applied to other ways of choosing
    tag_choice = opt.lots_for(opt.Problem(lots, buyers, tag_ranks, blocked),
                              opt.solve(opt.Problem(lots, buyers, tag_ranks, blocked), q))
    def strategy(key, name, note, idx):
        r = opt.evaluate(problem, q, idx)
        return {"key": key, "name": name, "note": note, "lots": [lots[i]["id"] for i in idx],
                "spent": r["spent"], "gross_margin": r["gross_margin"], "value": r["value"],
                "unplaced_capital": r["unplaced_capital"], "pieces": len(r["picks"])}

    compare = [
        *([strategy("plan", "Your parcel", "What you intend to buy, scored by the same rules", opt.lots_for(problem, mine))] if mine["picks"] else []),
        strategy("book", "THE BOOK", "Lots and buyers solved together", chosen),
        strategy("trophy", "Biggest stone first", "Most expensive lot that fits, repeat", opt.trophy_strategy(problem, q)),
        strategy("margin", "Best paper margin", "Largest markup, ignoring who buys", opt.margin_strategy(problem, q)),
        strategy("tags", "Tag matching", "Same solver, fit from tag overlap instead of BehaviorGPT", tag_choice),
    ]
    curve = cached_frontier(problem, q, blocked)

    fit = opt.fit_from_rank(ranks, req.fit_decay)
    demand = {}
    for i, l in enumerate(pool):
        resale = PIECES[l]["resale"]
        rows = sorted(({
            "collector": c["id"],
            "rank": int(ranks[i, j]),
            "rank_full": lens[c["id"]]["full"][l],
            "rank_orders": lens[c["id"]]["orders"][l],
            "rank_tags": tags[c["id"]][l],
            "fit": round(float(fit[i, j]), 3),
            "affordable": resale <= opt.limit(buyers[j], q) and buyers[j]["slots"] > 0,
            "vs_largest": round(resale / purchases(c)["high"], 2) if purchases(c)["high"] else None,
            "over_by": round(max(0.0, resale - opt.limit(buyers[j], q))),
            "stretch": round(max(0.0, resale - buyers[j]["capacity"])) if resale <= opt.limit(buyers[j], q) else 0,
            "passed": (l, c["id"]) in blocked,
        } for j, c in enumerate(COLLECTORS)), key=lambda x: (x["rank"], x["stretch"]))  # at equal rank, whoever fits best is named first
        demand[l] = rows

    # inventory: ranked only against the dealer's own stock, so #3 means third of what they hold for this collector
    stock = {c["id"]: within(raw[c["id"]]["full"], HOLD_IDS) for c in COLLECTORS}
    holdings = []
    for h in HOLDINGS:
        rows = sorted(({"collector": cid, "rank": ranks_[h["id"]]} for cid, ranks_ in stock.items()), key=lambda x: x["rank"])
        reach = sum(1 for x in rows if x["rank"] <= req.max_rank)
        holdings.append({"id": h["id"], "best": rows[:3], "reach": reach, "viewed_by": VIEWED_BY[h["id"]],
                         "status": "stale" if reach == 0 else "thin" if reach == 1 else "live"})
    in_stock = {cid: sorted(HOLD_IDS, key=ranks_.__getitem__)[:8] for cid, ranks_ in stock.items()}

    drift = {}
    for c in COLLECTORS:
        cid = c["id"]
        moves = sorted(pool, key=lambda l: lens[cid]["full"][l] - lens[cid]["orders"][l])
        gap = float(np.mean([abs(lens[cid]["full"][l] - lens[cid]["orders"][l]) for l in pool])) if pool else 0.0
        drift[cid] = {"gap": round(gap, 1), "rising": moves[:3], "fading": moves[-3:][::-1]}

    return {
        "portfolio": base,
        "plan": mine,
        "next": nxt,
        "compare": compare,
        "frontier": curve,
        "demand": demand,
        "holdings": holdings,
        "in_stock": in_stock,
        "drift": drift,
        "meta": {
            "source": "live" if "live" in sources else ("cache" if "cache" in sources else "snapshot"),
            "rank_ms": round(rank_ms), "solve_ms": round(solve_ms),
            "calls": 2 * len(COLLECTORS),
        },
    }


@app.get("/api/health")
def health():
    return {"ok": True, "live": ranker.client is not None, "lots": len(LOTS), "collectors": len(COLLECTORS)}


app.mount("/img", StaticFiles(directory=ROOT / "data" / "images"), name="img")
DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        return FileResponse(DIST / "index.html")
