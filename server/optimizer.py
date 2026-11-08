"""Capital-constrained acquisition: which lots to buy, and who each one is for.

Pieces are one of a kind and collectors have limited capacity, so choosing lots
and placing them are one decision. This solves them together as a MILP (HiGHS).

Nothing here is a probability. `fit` comes from where a lot sits in a collector's
BehaviorGPT ranking of the batch; `value` is the dealer's own margin assumption
weighted by that fit, minus a holding penalty for the part of the fit that is
missing. Both knobs are explicit and visible in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix


@dataclass
class Params:
    budget: float = 80_000
    fit_decay: float = 4.0        # rank at which fit has fallen to ~37%
    holding_penalty: float = 0.15 # share of ask charged for missing fit
    max_rank: int = 8             # a collector is only a candidate buyer down to this rank
    slots: int = 2                # lots earmarked per collector in one cycle
    resilience: float = 0.0       # 0 = maximize value, 1 = maximize worst single-buyer loss


@dataclass
class Problem:
    lots: list[dict]              # id, ask, resale (dealer's base estimate)
    collectors: list[dict]        # id, capacity (USD for this cycle)
    ranks: np.ndarray             # lots x collectors, 1 = top of that collector's batch ranking
    blocked: set[tuple[str, str]] = field(default_factory=set)  # (lot, collector) passes
    forced: set[str] = field(default_factory=set)  # what-if: buy these whatever the solver prefers


def fit_from_rank(ranks: np.ndarray, decay: float) -> np.ndarray:
    return np.exp(-(ranks - 1.0) / max(decay, 0.01))


def value_matrix(p: Problem, q: Params) -> np.ndarray:
    ask = np.array([l["ask"] for l in p.lots], float)[:, None]
    resale = np.array([l["resale"] for l in p.lots], float)[:, None]
    fit = fit_from_rank(p.ranks, q.fit_decay)
    return fit * (resale - ask) - (1 - fit) * q.holding_penalty * ask


def _eligible(p: Problem, q: Params) -> list[tuple[int, int]]:
    """Lot-collector pairs allowed: within rank, within capacity, not passed on."""
    pairs = []
    for i, lot in enumerate(p.lots):
        for j, c in enumerate(p.collectors):
            if p.ranks[i, j] > q.max_rank or lot["resale"] > c["capacity"]:
                continue
            if (lot["id"], c["id"]) in p.blocked:
                continue
            pairs.append((i, j))
    return pairs


def solve(p: Problem, q: Params) -> dict:
    """Pick lots and buyers. With resilience > 0, also protect the worst single buyer loss."""
    n, pairs = len(p.lots), _eligible(p, q)
    forced = {i for i, l in enumerate(p.lots) if l["id"] in p.forced}
    if not pairs and not forced:
        return _result(p, q, {})
    v = value_matrix(p, q)
    ask = np.array([l["ask"] for l in p.lots], float)
    resale = np.array([l["resale"] for l in p.lots], float)
    m = len(p.collectors)
    # variables: x[n], y[len(pairs)], then for resilience: y_s[m * len(pairs)], z
    np_ = len(pairs)
    use_scen = q.resilience > 0
    nvars = n + np_ + (m * np_ + 1 if use_scen else 0)
    rows, cols, vals, lo, hi = [], [], [], [], []
    r = 0

    def add(terms, l, h):
        nonlocal r
        for c_, a in terms:
            rows.append(r); cols.append(c_); vals.append(a)
        lo.append(l); hi.append(h); r += 1

    add([(i, ask[i]) for i in range(n)], -np.inf, q.budget)
    for i in range(n):  # a bought lot has exactly one intended buyer
        # a forced lot may end up with nobody, which is what a what-if needs to show
        add([(n + k, 1.0) for k, (a, _) in enumerate(pairs) if a == i] + [(i, -1.0)],
            -np.inf if i in forced else 0, 0)
    for j, c in enumerate(p.collectors):  # no collector is promised more than they can absorb
        idx = [k for k, (_, b) in enumerate(pairs) if b == j]
        if idx:
            add([(n + k, resale[pairs[k][0]]) for k in idx], -np.inf, c["capacity"])
            add([(n + k, 1.0) for k in idx], -np.inf, q.slots)

    c_obj = np.zeros(nvars)
    w_nom = 1 - q.resilience if use_scen else 1.0
    for k, (i, j) in enumerate(pairs):
        c_obj[n + k] = -w_nom * v[i, j]

    if use_scen:
        zi = nvars - 1
        c_obj[zi] = -q.resilience
        base = n + np_
        for s in range(m):  # re-placement after collector s walks; a lot may go unplaced
            at = lambda k: base + s * np_ + k
            for i in range(n):
                add([(at(k), 1.0) for k, (a, b) in enumerate(pairs) if a == i and b != s] + [(i, -1.0)],
                    -np.inf, 0)
            for j, c in enumerate(p.collectors):
                if j == s:
                    continue
                idx = [k for k, (_, b) in enumerate(pairs) if b == j]
                if idx:
                    add([(at(k), resale[pairs[k][0]]) for k in idx], -np.inf, c["capacity"])
                    add([(at(k), 1.0) for k in idx], -np.inf, q.slots)
            add([(zi, 1.0)] + [(at(k), -v[a, b]) for k, (a, b) in enumerate(pairs) if b != s]
                + [(i, q.holding_penalty * ask[i]) for i in range(n)], -np.inf, 0)

    integrality = np.zeros(nvars)
    integrality[: n + np_] = 1
    ub = np.ones(nvars)
    lb = np.zeros(nvars)
    for i in forced:
        lb[i] = 1
    if use_scen:
        lb[-1], ub[-1] = -np.inf, np.inf
    A = csr_matrix((vals, (rows, cols)), shape=(r, nvars))
    res = milp(c_obj, constraints=LinearConstraint(A, lo, hi), integrality=integrality,
               bounds=Bounds(lb, ub), options={"time_limit": 4.0, "mip_rel_gap": 0.002})
    if res.x is None:
        return _result(p, q, {})
    assign = {i: j for k, (i, j) in enumerate(pairs) if res.x[n + k] > 0.5}
    return _result(p, q, assign, chosen=sorted(set(assign) | forced))


def place(p: Problem, q: Params, chosen: list[int], drop: int | None = None) -> dict[int, int]:
    """Best placement of already-chosen lots. Lots with no eligible buyer stay unplaced."""
    pairs = [(i, j) for i, j in _eligible(p, q) if i in set(chosen) and j != drop]
    if not pairs:
        return {}
    v = value_matrix(p, q)
    resale = [l["resale"] for l in p.lots]
    n = len(pairs)
    rows, cols, vals, hi = [], [], [], []
    r = 0
    for i in chosen:
        idx = [k for k, (a, _) in enumerate(pairs) if a == i]
        if idx:
            rows += [r] * len(idx); cols += idx; vals += [1.0] * len(idx); hi.append(1.0); r += 1
    for j, c in enumerate(p.collectors):
        idx = [k for k, (_, b) in enumerate(pairs) if b == j]
        if idx:
            rows += [r] * len(idx); cols += idx; vals += [resale[pairs[k][0]] for k in idx]
            hi.append(c["capacity"]); r += 1
            rows += [r] * len(idx); cols += idx; vals += [1.0] * len(idx); hi.append(q.slots); r += 1
    # value here is relative to leaving a lot unplaced, so a bad buyer is never forced
    ask = [l["ask"] for l in p.lots]
    obj = [-(v[i, j] + q.holding_penalty * ask[i]) for i, j in pairs]
    res = milp(obj, constraints=LinearConstraint(csr_matrix((vals, (rows, cols)), shape=(r, n)), -np.inf, hi),
               integrality=np.ones(n), bounds=Bounds(0, 1), options={"time_limit": 2.0})
    if res.x is None:
        return {}
    return {pairs[k][0]: pairs[k][1] for k in range(n) if res.x[k] > 0.5}


def _result(p: Problem, q: Params, assign: dict[int, int], chosen: list[int] | None = None) -> dict:
    """Portfolio figures. `chosen` lists lots bought even if nobody is placed against them."""
    v = value_matrix(p, q)
    chosen = sorted(assign) if chosen is None else chosen
    fit = fit_from_rank(p.ranks, q.fit_decay)
    picks = []
    for i in chosen:
        lot = p.lots[i]
        j = assign.get(i)
        picks.append({
            "lot": lot["id"], "ask": lot["ask"], "resale": lot["resale"],
            "buyer": p.collectors[j]["id"] if j is not None else None,
            "rank": int(p.ranks[i, j]) if j is not None else None,
            "fit": round(float(fit[i, j]), 3) if j is not None else 0.0,
            "value": round(float(v[i, j]), 0) if j is not None else round(-q.holding_penalty * lot["ask"], 0),
        })
    spent = sum(x["ask"] for x in picks)
    return {
        "picks": picks,
        "spent": spent,
        "budget": q.budget,
        "unspent": q.budget - spent,
        "gross_margin": sum(x["resale"] - x["ask"] for x in picks),
        "value": round(sum(x["value"] for x in picks), 0),
        "unplaced_capital": sum(x["ask"] for x in picks if x["buyer"] is None),
    }


def evaluate(p: Problem, q: Params, chosen: list[int]) -> dict:
    """Score any set of lots by the same rules, whichever strategy picked them."""
    return _result(p, q, place(p, q, chosen), chosen=chosen)


def stress(p: Problem, q: Params, chosen: list[int]) -> list[dict]:
    """Every buyer walks, one at a time: what still has a home?"""
    base = evaluate(p, q, chosen)
    used = {x["buyer"] for x in base["picks"] if x["buyer"]}
    out = []
    for j, c in enumerate(p.collectors):
        if c["id"] not in used:
            continue
        r = _result(p, q, place(p, q, chosen, drop=j), chosen=chosen)
        out.append({
            "collector": c["id"],
            "value": r["value"],
            "value_lost": round(base["value"] - r["value"], 0),
            "unplaced_capital": r["unplaced_capital"],
            "unplaced": [x["lot"] for x in r["picks"] if x["buyer"] is None],
        })
    return sorted(out, key=lambda x: -x["value_lost"])


def frontier(p: Problem, q: Params, budgets: list[float]) -> list[dict]:
    """Value bought by each budget: where does the next dollar stop earning?"""
    out = []
    for b in budgets:
        r = solve(p, Params(**{**q.__dict__, "budget": b, "resilience": 0.0}))
        out.append({"budget": b, "value": r["value"], "spent": r["spent"], "pieces": len(r["picks"])})
    return out


# ---- comparison strategies: same budget, same scoring


def trophy_strategy(p: Problem, q: Params) -> list[int]:
    """Buy the most expensive thing that fits, then repeat."""
    left, out = q.budget, []
    for i in sorted(range(len(p.lots)), key=lambda i: -p.lots[i]["ask"]):
        if p.lots[i]["ask"] <= left:
            out.append(i)
            left -= p.lots[i]["ask"]
    return out


def margin_strategy(p: Problem, q: Params) -> list[int]:
    """Largest total paper margin under budget, ignoring who would buy."""
    margin = np.array([l["resale"] - l["ask"] for l in p.lots], float)
    ask = np.array([l["ask"] for l in p.lots], float)
    res = milp(-margin, constraints=LinearConstraint(csr_matrix(ask[None, :]), -np.inf, q.budget),
               integrality=np.ones(len(ask)), bounds=Bounds(0, 1))
    return [i for i, x in enumerate(res.x) if x > 0.5] if res.x is not None else []


def lots_for(p: Problem, r: dict) -> list[int]:
    idx = {l["id"]: i for i, l in enumerate(p.lots)}
    return [idx[x["lot"]] for x in r["picks"]]
