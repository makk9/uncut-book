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

# Wall-clock safety limits, not tuning. Real solves finish at the first node in under a second on
# one core, but a limit close to that makes the answer depend on the host's CPU: at 0.1 CPU a 4s
# limit returned a worse portfolio. Anything that does hit a limit is counted and shown in the UI.
SOLVE_SECONDS = 30.0
PLACE_SECONDS = 10.0
_early_stops = 0


def bounded_milp(*args, **kwargs):
    global _early_stops
    res = milp(*args, **kwargs)
    if res.status == 1:  # HiGHS: stopped at the limit, so the answer may not be the best one
        _early_stops += 1
    return res


def early_stops() -> int:
    """How many solves have stopped at a limit since the server started."""
    return _early_stops


@dataclass
class Params:
    budget: float = 80_000
    fit_decay: float = 4.0        # rank at which fit has fallen to ~37%
    holding_penalty: float = 0.15 # share of ask charged for missing fit
    max_rank: int = 8             # a collector is only a candidate buyer down to this rank
    slots: int = 2                # lots earmarked per collector in one cycle
    resilience: float = 0.0       # 0 = maximize value, 1 = maximize worst single-buyer loss
    capacity_tolerance: float = 0.25  # the furthest over capacity a collector can be placed
    stretch_cost: float = 0.50    # value lost per dollar placed over a collector's capacity


@dataclass
class Problem:
    lots: list[dict]              # id, ask, resale (dealer's base estimate)
    collectors: list[dict]        # id, capacity (USD for this cycle)
    ranks: np.ndarray             # lots x collectors, 1 = top of that collector's batch ranking
    blocked: set[tuple[str, str]] = field(default_factory=set)  # (lot, collector) passes
    forced: set[str] = field(default_factory=set)  # what-if: buy these whatever the solver prefers


def limit(c: dict, q: Params) -> float:
    """The most this collector can be placed against. Capacity itself is a rough estimate,
    so going over it costs value (`stretch_cost`) instead of ruling a lot out."""
    return c["capacity"] * (1 + q.capacity_tolerance)


def can_exceed(amounts: list[float], capacity: float, slots: int) -> bool:
    """Could this collector's largest `slots` lots go over capacity? If not, no overflow row is needed."""
    return sum(sorted(amounts, reverse=True)[:slots]) > capacity


def slots_of(c: dict, q: Params) -> int:
    """Pieces this collector can still take. Committed buys use up slots."""
    return c.get("slots", q.slots)


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
            if p.ranks[i, j] > q.max_rank or lot["resale"] > limit(c, q):
                continue
            if (lot["id"], c["id"]) in p.blocked:
                continue
            pairs.append((i, j))
    return pairs


def solve(p: Problem, q: Params, gap: float = 0.002, time_limit: float = SOLVE_SECONDS) -> dict:
    """Pick lots and buyers. With resilience > 0, also protect the worst single buyer loss."""
    n, pairs = len(p.lots), _eligible(p, q)
    forced = {i for i, l in enumerate(p.lots) if l["id"] in p.forced}
    if not pairs and not forced:
        return _result(p, q, {})
    v = value_matrix(p, q)
    ask = np.array([l["ask"] for l in p.lots], float)
    resale = np.array([l["resale"] for l in p.lots], float)
    m = len(p.collectors)
    # variables: x[n], y[len(pairs)], over[m], then for resilience: y_s[m * len(pairs)], over_s[m * m], z
    np_ = len(pairs)
    use_scen = q.resilience > 0
    over_at = n + np_
    nvars = n + np_ + m + (m * np_ + m * m + 1 if use_scen else 0)
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
            add([(n + k, resale[pairs[k][0]]) for k in idx], -np.inf, limit(c, q))
            if can_exceed([resale[pairs[k][0]] for k in idx], c["capacity"], slots_of(c, q)):
                add([(n + k, resale[pairs[k][0]]) for k in idx] + [(over_at + j, -1.0)], -np.inf, c["capacity"])
                for k in idx:  # one lot's own overflow is known exactly, which keeps the solve fast
                    extra = resale[pairs[k][0]] - c["capacity"]
                    if extra > 0:
                        add([(n + k, extra), (over_at + j, -1.0)], -np.inf, 0)
            add([(n + k, 1.0) for k in idx], -np.inf, slots_of(c, q))

    c_obj = np.zeros(nvars)
    w_nom = 1 - q.resilience if use_scen else 1.0
    for k, (i, j) in enumerate(pairs):
        # an unplaced forced lot still costs its holding charge, so placing one saves that charge
        saved = q.holding_penalty * ask[i] if i in forced else 0.0
        c_obj[n + k] = -w_nom * (v[i, j] + saved)
    for j in range(m):
        c_obj[over_at + j] = w_nom * q.stretch_cost

    if use_scen:
        zi = nvars - 1
        c_obj[zi] = -q.resilience
        base = over_at + m
        over_s_at = base + m * np_
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
                    add([(at(k), resale[pairs[k][0]]) for k in idx], -np.inf, limit(c, q))
                    if can_exceed([resale[pairs[k][0]] for k in idx], c["capacity"], slots_of(c, q)):
                        add([(at(k), resale[pairs[k][0]]) for k in idx] + [(over_s_at + s * m + j, -1.0)],
                            -np.inf, c["capacity"])
                    add([(at(k), 1.0) for k in idx], -np.inf, slots_of(c, q))
            add([(zi, 1.0)] + [(at(k), -v[a, b]) for k, (a, b) in enumerate(pairs) if b != s]
                + [(i, q.holding_penalty * ask[i]) for i in range(n)]
                + [(over_s_at + s * m + j, q.stretch_cost) for j in range(m)], -np.inf, 0)

    integrality = np.zeros(nvars)
    integrality[: n + np_] = 1
    ub = np.ones(nvars)
    lb = np.zeros(nvars)
    for i in forced:
        lb[i] = 1
    ub[over_at:over_at + m] = np.inf
    if use_scen:
        ub[over_s_at:over_s_at + m * m] = np.inf
        lb[-1], ub[-1] = -np.inf, np.inf
    A = csr_matrix((vals, (rows, cols)), shape=(r, nvars))
    res = bounded_milp(c_obj, constraints=LinearConstraint(A, lo, hi), integrality=integrality,
                       bounds=Bounds(lb, ub), options={"time_limit": time_limit, "mip_rel_gap": gap})
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
    m = len(p.collectors)
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
            hi.append(limit(c, q)); r += 1
            if can_exceed([resale[pairs[k][0]] for k in idx], c["capacity"], slots_of(c, q)):
                rows += [r] * (len(idx) + 1); cols += idx + [n + j]
                vals += [resale[pairs[k][0]] for k in idx] + [-1.0]; hi.append(c["capacity"]); r += 1
                for k in idx:
                    extra = resale[pairs[k][0]] - c["capacity"]
                    if extra > 0:
                        rows += [r, r]; cols += [k, n + j]; vals += [extra, -1.0]; hi.append(0.0); r += 1
            rows += [r] * len(idx); cols += idx; vals += [1.0] * len(idx); hi.append(slots_of(c, q)); r += 1
    # value here is relative to leaving a lot unplaced, so a bad buyer is never forced
    ask = [l["ask"] for l in p.lots]
    obj = [-(v[i, j] + q.holding_penalty * ask[i]) for i, j in pairs] + [q.stretch_cost] * m
    integrality = np.array([1.0] * n + [0.0] * m)
    upper = np.array([1.0] * n + [np.inf] * m)
    res = bounded_milp(obj, constraints=LinearConstraint(csr_matrix((vals, (rows, cols)), shape=(r, n + m)), -np.inf, hi),
                       integrality=integrality, bounds=Bounds(0, upper), options={"time_limit": PLACE_SECONDS, "mip_rel_gap": 0.005})
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
    placed = [0.0] * len(p.collectors)
    for i, j in assign.items():
        placed[j] += p.lots[i]["resale"]
    stretch = q.stretch_cost * sum(max(0.0, total - c["capacity"]) for total, c in zip(placed, p.collectors))
    return {
        "picks": picks,
        "spent": spent,
        "budget": q.budget,
        "unspent": q.budget - spent,
        "gross_margin": sum(x["resale"] - x["ask"] for x in picks),
        "value": round(sum(x["value"] for x in picks) - stretch, 0),
        "stretch_cost": round(stretch, 0),
        "unplaced_capital": sum(x["ask"] for x in picks if x["buyer"] is None),
    }


def evaluate(p: Problem, q: Params, chosen: list[int]) -> dict:
    """Score any set of lots by the same rules, whichever strategy picked them."""
    return _result(p, q, place(p, q, chosen), chosen=chosen)


def _swap_is_tie(p: Problem, q: Params, assign: dict[int, int], i: int, k: int) -> bool:
    """Could lot i move to collector k with nothing else changing?

    Equal rank is not enough. The other collector must be eligible and have a free slot and room
    under their limit with their other pieces still in place, and the over-capacity charge must
    come out the same.
    """
    j = assign[i]
    if k == j or (i, k) not in _eligible(p, q):
        return False
    v = value_matrix(p, q)
    if not np.isclose(v[i, k], v[i, j]):
        return False
    c = p.collectors[k]
    resale = p.lots[i]["resale"]
    total = lambda b: sum(p.lots[a]["resale"] for a, b_ in assign.items() if b_ == b)
    if sum(b == k for b in assign.values()) + 1 > slots_of(c, q) or total(k) + resale > limit(c, q):
        return False
    over = lambda b, amount: max(0.0, amount - p.collectors[b]["capacity"])
    return bool(np.isclose(over(j, total(j)) + over(k, total(k)),
                           over(j, total(j) - resale) + over(k, total(k) + resale)))


def _assignment(p: Problem, result: dict) -> dict[int, int]:
    lot_at = {l["id"]: i for i, l in enumerate(p.lots)}
    col_at = {c["id"]: j for j, c in enumerate(p.collectors)}
    return {lot_at[x["lot"]]: col_at[x["buyer"]] for x in result["picks"] if x["buyer"]}


def buyer_ties(p: Problem, q: Params, result: dict) -> dict[str, list[str]]:
    """Lots whose buyer could be swapped with nothing changing: {lot: other equally good collectors}."""
    assign = _assignment(p, result)
    ties: dict[str, list[str]] = {}
    for i in assign:
        for k, c in enumerate(p.collectors):
            if _swap_is_tie(p, q, assign, i, k):
                ties.setdefault(p.lots[i]["id"], []).append(c["id"])
    return ties


def keep_buyers(p: Problem, q: Params, result: dict, prefer: dict[str, str]) -> dict:
    """Break exact ties toward the buyer the dealer was already shown. Never changes the score:
    anything short of an exact tie keeps the placement the solver chose."""
    lot_at = {l["id"]: i for i, l in enumerate(p.lots)}
    col_at = {c["id"]: j for j, c in enumerate(p.collectors)}
    assign = _assignment(p, result)
    changed = False
    for lot, cid in prefer.items():
        i, k = lot_at.get(lot), col_at.get(cid)
        if i in assign and k is not None and _swap_is_tie(p, q, assign, i, k):
            assign[i] = k
            changed = True
    return _result(p, q, assign, chosen=[lot_at[x["lot"]] for x in result["picks"]]) if changed else result


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
        # a trend line for the chart: within-capacity placement solves in milliseconds, so a
        # signal or setting change isn't held up by 20 harder solves
        r = solve(p, Params(**{**q.__dict__, "budget": b, "resilience": 0.0, "capacity_tolerance": 0.0}))
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
    if not p.lots:
        return []
    margin = np.array([l["resale"] - l["ask"] for l in p.lots], float)
    ask = np.array([l["ask"] for l in p.lots], float)
    res = bounded_milp(-margin, constraints=LinearConstraint(csr_matrix(ask[None, :]), -np.inf, q.budget),
                       integrality=np.ones(len(ask)), bounds=Bounds(0, 1), options={"time_limit": SOLVE_SECONDS})
    return [i for i, x in enumerate(res.x) if x > 0.5] if res.x is not None else []


def lots_for(p: Problem, r: dict) -> list[int]:
    idx = {l["id"]: i for i, l in enumerate(p.lots)}
    return [idx[x["lot"]] for x in r["picks"]]
