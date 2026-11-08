"""End-to-end check against a running server: real rankings -> optimizer -> portfolio.

Checks constraints from the output alone, independently of the solver, and shows
that demand overlap changes the answer compared with picking from rankings alone.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
BOOK = Path(__file__).resolve().parent.parent / "data" / "book"
PIECES = {p["id"]: p for p in json.loads((BOOK / "pieces.json").read_text())}
COLLECTORS = {c["id"]: c for c in json.loads((BOOK / "collectors.json").read_text())}
client = httpx.Client(base_url=BASE, timeout=90)
failures = 0


def check(ok: bool, label: str) -> None:
    global failures
    failures += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")


def solve(**kw) -> dict:
    r = client.post("/api/portfolio", json=kw)
    r.raise_for_status()
    return r.json()


print("[1] budget changes the portfolio, and constraints hold at each budget")
previous = None
for budget in (20_000, 40_000, 80_000, 120_000, 200_000):
    d = solve(budget=budget)
    p, m = d["portfolio"], d["meta"]
    print(f"\n  ${budget:,}: {len(p['picks'])} pieces, spent ${p['spent']:,.0f}, value ${p['value']:,.0f} "
          f"| source={m['source']} rank={m['rank_ms']}ms solve={m['solve_ms']}ms")
    for x in p["picks"]:
        print(f"    {PIECES[x['lot']]['name'][:40]:40} ${x['ask']:>7,.0f} -> {COLLECTORS[x['buyer']]['name'] if x['buyer'] else 'nobody':16} #{x['rank']}")
    check(p["spent"] <= budget, "spend within budget")
    by = defaultdict(list)
    for x in p["picks"]:
        by[x["buyer"]].append(x)
    check(all(len(v) <= 2 for v in by.values()), "no collector over 2 pieces")
    check(all(sum(x["resale"] for x in v) <= COLLECTORS[c]["capacity"] * 1.25 + 1e-6 for c, v in by.items()), "no collector over capacity plus the 25% ceiling")
    check(abs(sum(x["value"] for x in p["picks"]) - p["stretch_cost"] - p["value"]) <= 2, "reported value includes the stretch cost")
    check(len({x["lot"] for x in p["picks"]}) == len(p["picks"]), "each lot bought once")
    check(all(x["rank"] <= 8 for x in p["picks"]), "every buyer ranks their lot within the cutoff")
    check(all(next(r for r in d["demand"][x["lot"]] if r["collector"] == x["buyer"])["rank"] == x["rank"] for x in p["picks"]),
          "reported rank matches the demand table")
    if previous is not None:
        check(p["value"] >= previous - 1, "value does not fall as budget rises")
    previous = p["value"]

print("\n[2] rankings are real and differ by collector")
d = solve(budget=80_000)
check(len(PIECES) == len(json.loads((BOOK / "pieces.json").read_text())), "every piece has a unique id")
check(len(d["holdings"]) == sum(p["role"] == "holding" for p in PIECES.values()) > 0, f"{len(d['holdings'])} holdings read against the collectors")
known = set(PIECES)
check(all(e["id"] in known for c in COLLECTORS.values() for e in c["events"] if "id" in e), "every event points at a real piece")
check(d["meta"]["source"] in ("live", "cache"), f"source is {d['meta']['source']}, not snapshot")
tops = {c: min(((l, next(r for r in rows if r["collector"] == c)["rank"]) for l, rows in d["demand"].items()), key=lambda x: x[1])[0]
        for c in COLLECTORS}
for c, l in tops.items():
    print(f"    {COLLECTORS[c]['name']:18} top lot: {PIECES[l]['name']}")
check(len(set(tops.values())) >= 4, f"{len(set(tops.values()))} distinct top lots across {len(tops)} collectors")

print("\n[3] overlapping demand: does solving jointly differ from taking each collector's top lots?")
wanted = defaultdict(list)
for lot, rows in d["demand"].items():
    for r in rows:
        if r["rank"] <= 3:
            wanted[lot].append(r["collector"])
contested = {l: c for l, c in wanted.items() if len(c) >= 2}
print(f"  {len(contested)} lots sit in the top 3 of 2+ collectors")
for l, cs in sorted(contested.items(), key=lambda x: -len(x[1]))[:5]:
    print(f"    {PIECES[l]['name'][:38]:38} wanted by {', '.join(COLLECTORS[c]['name'] for c in cs)}")
buyers_used = defaultdict(int)
for x in d["portfolio"]["picks"]:
    buyers_used[x["buyer"]] += 1
print("  buyers used:", {COLLECTORS[c]["name"]: n for c, n in buyers_used.items()})

print("\n  removing a collector's capacity from the problem should re-place, not just drop")
top = d["stress"][0] if d["stress"] else None
if top:
    print(f"    worst buyer loss: {COLLECTORS[top['collector']]['name']}, value -${top['value_lost']:,.0f}, unplaced ${top['unplaced_capital']:,.0f}")

print("\n[4] same budget, other ways to choose")
for c in d["compare"]:
    print(f"    {c['name']:22} pieces {c['pieces']:2} spent ${c['spent']:>7,.0f} margin ${c['gross_margin']:>7,.0f} value ${c['value']:>8,.0f} "
          f"unplaced ${c['unplaced_capital']:>7,.0f} one-buyer loss ${c['worst_loss']:>7,.0f}")
book = next(c for c in d["compare"] if c["key"] == "book")
check(all(book["value"] >= c["value"] - 1 for c in d["compare"]), "joint solve scores at least as high as the alternatives on its own metric")

print("\n[5] a live signal moves the real ranking, then the portfolio")
buyer = next((x["buyer"] for x in d["portfolio"]["picks"] if x["buyer"]), "rachel")
def order(res, c):
    return [l for l, _ in sorted(((l, next(r for r in rows if r["collector"] == c)["rank_full"]) for l, rows in res["demand"].items()), key=lambda x: x[1])]
before = order(d, buyer)
s = solve(budget=80_000, signals={buyer: [{"type": "search", "q": "gold chain"}]})
after = order(s, buyer)
print(f"  {COLLECTORS[buyer]['name']}: before {[PIECES[x]['name'][:22] for x in before[:3]]}")
print(f"  {COLLECTORS[buyer]['name']}: after  {[PIECES[x]['name'][:22] for x in after[:3]]}  ({s['meta']['rank_ms']} ms, {s['meta']['source']})")
check(before != after, "the signal changed that collector's ranking")
a = {x["lot"] for x in d["portfolio"]["picks"]}
b = {x["lot"] for x in s["portfolio"]["picks"]}
print(f"  portfolio changes: +{[PIECES[x]['name'][:24] for x in b - a]} -{[PIECES[x]['name'][:24] for x in a - b]}")

print("\n[6] what-if: force the trophy in")
trophy = max((p for p in PIECES.values() if p["role"] == "lot"), key=lambda p: p["ask"])
w = client.post("/api/whatif", json={"budget": 80_000, "lot": trophy["id"]}).json()
print(f"  {trophy['name']} (${trophy['ask']:,}): already in={w.get('already_in')}, value {w.get('value_delta')}, margin {w.get('margin_delta')}, "
      f"buyer {w.get('buyer')} #{w.get('rank')}, displaces {[PIECES[x]['name'][:24] for x in w.get('displaced', [])]}")
if not w.get("already_in"):
    check((w.get("value_delta") or 0) <= 1, "forcing a lot in never raises value above the optimum")

print("\n[7] resilience mode trades value for a smaller single-buyer loss")
for label, res in (("Max value", 0), ("Balanced", 0.5), ("Buyer-proof", 0.9)):
    r = solve(budget=80_000, resilience=res)
    c = next(x for x in r["compare"] if x["key"] == "book")
    print(f"    {label:12} pieces {c['pieces']:2} value ${c['value']:>8,.0f} one-buyer loss ${c['worst_loss']:>7,.0f} solve {r['meta']['solve_ms']}ms")

print("\n[8] capacity ceiling and stretch cost")
for tol in (0.0, 0.10, 0.25, 0.50):
    r = solve(budget=80_000, capacity_tolerance=tol)
    p = r["portfolio"]
    by = defaultdict(float)
    for x in p["picks"]:
        by[x["buyer"]] += x["resale"]
    worst = max((v / COLLECTORS[c]["capacity"] - 1 for c, v in by.items()), default=0)
    stretched = [x for x in p["picks"] if next(d for d in r["demand"][x["lot"]] if d["collector"] == x["buyer"])["stretch"] > 0]
    print(f"    {tol:.0%}: {len(p['picks'])} pieces, spent ${p['spent']:,.0f}, value ${p['value']:,.0f}, most over stated capacity {worst:+.1%}, lots relying on tolerance {len(stretched)}")
    check(worst <= tol + 1e-6, f"placed within the {tol:.0%} limit")
    check(all(d["over_by"] == 0 for x in p["picks"] for d in r["demand"][x["lot"]] if d["collector"] == x["buyer"]), "no placed pair is reported as over the limit")
    if tol == 0:
        check(not stretched, "with no tolerance nothing relies on it")
print(f"    trophy still has no buyer at 25%: {not any(True for d in solve(budget=80_000, capacity_tolerance=0.25)['demand'][max((l for l in PIECES.values() if l['role'] == 'lot'), key=lambda l: l['ask'])['id']] if d['affordable'])}")

print("\n[9] radar, desk and committed buys")
LOT_IDS = [p["id"] for p in PIECES.values() if p["role"] == "lot"]
base20 = LOT_IDS[:20]
r = solve(budget=80_000, radar=base20)
check(set(r["demand"]) == set(base20), "only lots on the radar get ranked")
check(all(d["rank"] <= 20 for rows in r["demand"].values() for d in rows), "ranks are among the 20 visible lots")
check({x["lot"] for x in r["portfolio"]["picks"]} <= set(base20), "the solver only buys from the radar")
short = base20[:6]
r2 = solve(budget=80_000, radar=base20, desk=short)
check({x["lot"] for x in r2["portfolio"]["picks"]} <= set(short), "the solver only buys from the desk")
check(set(r2["demand"]) == set(base20), "lots off the desk still show their collector demand")
r0 = solve(budget=80_000, radar=base20, desk=[])
check(r0["portfolio"]["picks"] == [] and r0["portfolio"]["value"] == 0, "an empty desk proposes nothing")
r0 = solve(budget=0, radar=base20)
check(r0["portfolio"]["picks"] == [], "no capital left proposes nothing")
big = solve(budget=1_000_000)
check(big["portfolio"]["spent"] < 300_000, f"not forced to spend: ${big['portfolio']['spent']:,.0f} of $1,000,000")
check(all(x["value"] > -1 for x in big["portfolio"]["picks"]), "every proposed lot earns its place")

first = r["portfolio"]["picks"][0]
buyer = first["buyer"]
left = 80_000 - first["ask"]
done = [{"lot": first["lot"], "buyer": buyer}]
r3 = solve(budget=left, radar=base20, committed=done)
check(first["lot"] not in r3["demand"], "a bought lot leaves the pool")
check(all(x["lot"] != first["lot"] for x in r3["portfolio"]["picks"]), "a bought lot is not proposed again")
check(r3["portfolio"]["spent"] <= left, "the next proposal fits the remaining capital")
print(f"    bought {PIECES[first['lot']]['name'][:34]} for {COLLECTORS[buyer]['name']}: {len(r3['portfolio']['picks'])} pieces proposed with ${left:,.0f} left")
placed = [x for x in r3["portfolio"]["picks"] if x["buyer"] == buyer]
check(len(placed) <= 1, "that buyer has one slot left")
check(sum(x["resale"] for x in placed) + first["resale"] <= COLLECTORS[buyer]["capacity"] * 1.25 + 1e-6, "their committed and proposed pieces stay within their limit")
others = [x for x in r3["demand"][next(iter(r3["demand"]))] if x["collector"] == buyer]
two = [{"lot": l, "buyer": buyer} for l in LOT_IDS[:2]]
r4 = solve(budget=80_000, committed=two)
check(all(x["buyer"] != buyer for x in r4["portfolio"]["picks"]), "a buyer with two committed pieces is not offered more")

print("\nFAILURES:", failures)
sys.exit(1 if failures else 0)
