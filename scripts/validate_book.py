"""Does the final catalog behave sensibly under real BehaviorGPT inference?

Answers four questions. All collectors are invented and their tastes are written in
the same tags the baseline uses, so the baseline has a built-in advantage on taste
scores. Nothing here is evidence about real collectors or real sales.

1. How do BehaviorGPT and a tag-matching baseline compare, and where do they disagree?
2. Do rankings move sensibly when a history changes?
3. Does the solver respect budget, capacity and overlap on hand-checkable problems?
4. Does solving jointly beat taking each collector's favorite?
"""
import json
import os
import statistics as st
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from behaviorgpt import Order, Search, UnboxAIClient, View
from dotenv import load_dotenv
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
load_dotenv(ROOT / ".env")

from build_book import PERSONAS, affinity  # noqa: E402
from server import optimizer as opt  # noqa: E402

CATALOG = sys.argv[1] if len(sys.argv) > 1 else os.environ["UNBOXAI_CATALOG_ID"]
BOOK = ROOT / "data" / "book"
P = {p["id"]: p for p in json.loads((BOOK / "pieces.json").read_text())}
CS = json.loads((BOOK / "collectors.json").read_text())
PHASES = {p[0]: p[4] for p in PERSONAS}
LOTS = [p for p in P.values() if p["role"] == "lot"]
IDS = [p["id"] for p in LOTS]
HIST = [p for p in P.values() if p["role"] == "history"]
client = UnboxAIClient(market="us", timezone="America/New_York")
failures = 0


def check(ok, label):
    global failures
    failures += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")


def sdk(rows):
    out = []
    for e in rows:
        out.append(Search(e["q"]) if e["type"] == "search" else View(e["id"]) if e["type"] == "view" else Order([e["id"]]))
    return out


def rank(rows, ids=IDS):
    r = client.complete(sdk(rows), limit=100, filters={"id": ids}, catalog_id=CATALOG, register_event=False)
    got = [i.id for i in r.items]
    return got + [x for x in ids if x not in got]


def tags_of(p):
    return {f"form:{p['form']}", f"era:{p['era']}", f"style:{p['style']}",
            *[f"stone:{s}" for s in p["stones"]], *[f"metal:{m}" for m in p["metals"]]}


def tag_rank(rows, ids=IDS):
    profile = Counter()
    for e in rows:
        if e["type"] in ("view", "order"):
            for t in tags_of(P[e["id"]]):
                profile[t] += 3 if e["type"] == "order" else 1
    return sorted(ids, key=lambda i: -sum(profile[t] for t in tags_of(P[i])))


def blend(c, recency=0.6):
    full = {x: n + 1 for n, x in enumerate(rank(c["events"]))}
    orders = {x: n + 1 for n, x in enumerate(rank([e for e in c["events"] if e["type"] == "order"]))}
    return {x: recency * full[x] + (1 - recency) * orders[x] for x in IDS}


def taste_score(order, weights):
    aff = [affinity(weights, P[x]) for x in order]
    return -spearmanr(range(len(order)), aff).statistic if len(set(aff)) > 1 else 0.0


print(f"catalog {CATALOG}: {len(P)} pieces, {sum(1 for p in P.values() if p.get('image_url'))} with photos")

print("\n[1] BehaviorGPT vs tag matching")
positions = {c["id"]: blend(c) for c in CS}
book = {x: st.mean(p[x] for p in positions.values()) for x in IDS}
orders = {k: sorted(IDS, key=lambda x: (p[x] - (book[x] - p[x]), p[x])) for k, p in positions.items()}
raw_first = Counter(min(IDS, key=lambda x: p[x]) for p in positions.values())
print(f"  before the relative adjustment: {len(raw_first)} distinct #1 lots, most common x{raw_first.most_common(1)[0][1]}")
tagged = {c["id"]: tag_rank(c["events"]) for c in CS}
b_scores, t_scores, agree = [], [], []
for c in CS:
    w = PHASES[c["id"]][-1][0]
    b, t = orders[c["id"]], tagged[c["id"]]
    b_scores.append(taste_score(b, w))
    t_scores.append(taste_score(t, w))
    agree.append(spearmanr([b.index(x) for x in IDS], [t.index(x) for x in IDS]).statistic)
    print(f"\n  {c['name']}: {c['blurb'][:70]}")
    print("    BehaviorGPT", " | ".join(P[x]["name"][:30] for x in b[:3]))
    print("    Tags       ", " | ".join(P[x]["name"][:30] for x in t[:3]))
print(f"\n  taste agreement: BehaviorGPT {st.mean(b_scores):+.2f}, tags {st.mean(t_scores):+.2f}; tags favored by construction")
print(f"  BehaviorGPT vs tags: correlation {st.mean(agree):+.2f}")
firsts = Counter(o[0] for o in orders.values())
print(f"  {len(firsts)} distinct #1 lots across {len(CS)}; most common {P[firsts.most_common(1)[0][0]]['name'][:34]} x{firsts.most_common(1)[0][1]}")

print("\n  held-out test: hide each collector's last purchase, rank it among 19 other history pieces")
b_ranks, t_ranks = [], []
import random
rng = random.Random(5)
for c in CS:
    positions = [i for i, e in enumerate(c["events"]) if e["type"] == "order"]
    for pos in positions[-2:]:
        target = c["events"][pos]["id"]
        before = [e for e in c["events"][:pos] if not (e.get("id") == target)]
        if len(before) < 5:
            continue
        seen = {e["id"] for e in before if "id" in e} | {target}
        others = rng.sample([p["id"] for p in HIST if p["id"] not in seen], k=min(19, len([p for p in HIST if p["id"] not in seen])))
        cand = others + [target]
        b_ranks.append(rank(before, cand).index(target) + 1)
        t_ranks.append(tag_rank(before, cand).index(target) + 1)
n = len(b_ranks)
print(f"    {n} tests. mean rank of 20: BehaviorGPT {st.mean(b_ranks):.1f} (top 3 {sum(x <= 3 for x in b_ranks) / n:.0%}), "
      f"tags {st.mean(t_ranks):.1f} (top 3 {sum(x <= 3 for x in t_ranks) / n:.0%}), random 10.5 (top 3 15%)")
print("    purchases were simulated from the same tags, so this measures fit to the simulation")

print("\n[2] do rankings move sensibly when a history changes?")
print("  a) taste shift: append a burst of another taste, does ranking move toward it?")
moved, total = 0, 0
pairs = [("rachel", "sofia"), ("julian", "marcus"), ("naomi", "theo"), ("dev", "claudia"), ("margot", "andre"), ("claudia", "ines")]
for a, b in pairs:
    ca = next(c for c in CS if c["id"] == a)
    w = PHASES[b][-1][0]
    burst = sorted(HIST, key=lambda p: -affinity(w, p))[:5]
    before = taste_score(rank(ca["events"]), w)
    after = taste_score(rank(ca["events"] + [{"type": "view", "id": p["id"]} for p in burst]), w)
    total += 1
    moved += after > before
    print(f"     {a} + {b}'s taste: agreement {before:+.2f} -> {after:+.2f}")
check(moved >= total - 1, f"{moved} of {total} moved toward the appended taste")

print("  b) drift: for collectors built with two phases, which phase does the ranking follow?")
follow = 0
drifters = [c for c in CS if len(PHASES[c["id"]]) > 1]
for c in drifters:
    old, new = PHASES[c["id"]][0][0], PHASES[c["id"]][-1][0]
    full = rank(c["events"])
    bought = rank([e for e in c["events"] if e["type"] == "order"])
    print(f"     {c['name']:16} full history: new taste {taste_score(full, new):+.2f}, old taste {taste_score(full, old):+.2f}")
    follow += taste_score(full, new) > taste_score(full, old)
check(follow >= len(drifters) - 1, f"{follow} of {len(drifters)} follow their recent taste")

print("  c) order: same events reversed should change the ranking")
overlaps = []
for c in drifters:
    fw = rank(c["events"])
    bw = rank(list(reversed(c["events"])))
    overlaps.append(len(set(fw[:5]) & set(bw[:5])))
print(f"     top-5 overlap after reversing: {overlaps}")
check(any(o < 5 for o in overlaps), "order changes the ranking")

print("  d) a signal should favor what was asked about")
hits = 0
tests = [("rachel", "emerald ring", "Emerald"), ("julian", "pearl necklace", "Pearl"), ("dev", "sapphire ring", "Sapphire"),
         ("claudia", "ruby ring", "Ruby"), ("andre", "diamond", "Diamond"), ("margot", "aquamarine", "Aquamarine")]
for cid, q, stone in tests:
    c = next(x for x in CS if x["id"] == cid)
    wanted = [x for x in IDS if stone in P[x]["stones"]]
    base = st.mean(rank(c["events"]).index(x) + 1 for x in wanted)
    asked = st.mean(rank(c["events"] + [{"type": "search", "q": q}]).index(x) + 1 for x in wanted)
    hits += asked < base
    print(f"     {cid} asks about {q!r}: mean rank of {stone} lots {base:.1f} -> {asked:.1f}")
check(hits >= len(tests) - 1, f"{hits} of {len(tests)} moved the asked-for lots up")

print("\n[3] hand-checkable optimizer problems")


def small(lots, collectors, ranks, **kw):
    p = opt.Problem([{"id": i, "ask": a, "resale": r} for i, a, r in lots],
                    [{"id": i, "capacity": cap} for i, cap in collectors], np.array(ranks, float))
    return opt.solve(p, opt.Params(capacity_tolerance=0.0, **kw))


r = small([("A", 10, 20)], [("x", 100), ("y", 100)], [[1, 1]], budget=100)
check(len(r["picks"]) == 1, "one lot wanted by two collectors is bought and placed once")
r = small([("A", 10, 20), ("B", 10, 20), ("C", 10, 20)], [("x", 100)], [[1], [2], [3]], budget=100, slots=2)
check(len(r["picks"]) == 2, "three lots wanted by one collector with two slots: only two bought")
r = small([("A", 10, 50), ("B", 10, 50)], [("x", 60), ("y", 60)], [[1, 2], [1, 2]], budget=100, slots=2)
check({x["buyer"] for x in r["picks"]} == {"x", "y"}, "capacity forces the second lot to a second collector")
r = small([("A", 60, 90), ("B", 60, 90)], [("x", 100), ("y", 100)], [[1, 1], [1, 1]], budget=100)
check(len(r["picks"]) == 1 and r["spent"] <= 100, "two affordable lots that together exceed budget: only one")
r = small([("A", 10, 500)], [("x", 100)], [[1]], budget=100)
check(not r["picks"], "a lot nobody has capacity for is not bought")
r = small([("A", 10, 20), ("B", 10, 40)], [("x", 100)], [[1], [2]], budget=10)
check([x["lot"] for x in r["picks"]] == ["B"], "with budget for one, it takes the higher value lot")
p = opt.Problem([{"id": "A", "ask": 10, "resale": 20}], [{"id": "x", "capacity": 100}], np.array([[1.0]]), blocked={("A", "x")})
check(not opt.solve(p, opt.Params(budget=100, capacity_tolerance=0.0))["picks"], "a passed collector is not placed")

print("\n[4] overlap on the real rankings, $80k")
lots = [{"id": l["id"], "ask": l["ask"], "resale": l["resale"]} for l in LOTS]
buyers = [{"id": c["id"], "capacity": c["capacity"]} for c in CS]
ranks = np.array([[orders[c["id"]].index(l) + 1 for c in CS] for l in IDS], float)
problem = opt.Problem(lots, buyers, ranks)
q = opt.Params(budget=80_000)
joint = opt.solve(problem, q)
fav = list(dict.fromkeys(orders[c["id"]][0] for c in CS))
naive_all = [x for x in fav]
contested = Counter(orders[c["id"]][0] for c in CS)
print(f"  each collector's favorite: {len(fav)} lots for {len(CS)} collectors; "
      f"{sum(v - 1 for v in contested.values())} collectors share a favorite with someone else")
order_by_value = sorted(range(len(IDS)), key=lambda i: -max(opt.value_matrix(problem, q)[i]))
idx = {l: i for i, l in enumerate(IDS)}
left, naive = q.budget, []
for l in sorted(fav, key=lambda l: -max(opt.value_matrix(problem, q)[idx[l]])):
    if P[l]["ask"] <= left:
        naive.append(idx[l])
        left -= P[l]["ask"]
ne = opt.evaluate(problem, q, naive)
print(f"  favorites, best value first: {len(ne['picks'])} pieces, value ${ne['value']:,.0f}, unplaced ${ne['unplaced_capital']:,.0f}")
print(f"  joint solve:                 {len(joint['picks'])} pieces, value ${joint['value']:,.0f}, unplaced ${joint['unplaced_capital']:,.0f}")
check(joint["value"] >= ne["value"] - 1, "joint solve scores at least as high on the same rules")
check(joint["spent"] <= q.budget, "budget respected")
used = Counter(x["buyer"] for x in joint["picks"])
check(all(v <= q.slots for v in used.values()), "slots respected")
for c in CS:
    placed = sum(x["resale"] for x in joint["picks"] if x["buyer"] == c["id"])
    if placed > c["capacity"] * 1.1 + 1e-6:
        check(False, f"{c['name']} over capacity")
print("\nFAILURES:", failures)
sys.exit(1 if failures else 0)
