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
sold = {e["id"] for c in COLLECTORS.values() for e in c["events"] if e["type"] == "order"}
check(all((p["role"] == "history") == (i in sold) for i, p in PIECES.items() if p["role"] != "lot"), "every sold piece is out of inventory, every unsold piece is in it")
check(all(1 <= r["rank"] <= len(d["holdings"]) for h in d["holdings"] for r in h["best"]), "inventory ranks are among the dealer's own stock")
check(all(i in {h["id"] for h in d["holdings"]} for ids in d["in_stock"].values() for i in ids) and set(d["in_stock"]) == set(COLLECTORS), "each collector's in-stock list comes from inventory")
check(all(any(e["type"] == "view" and e["id"] == h["id"] for e in COLLECTORS[c]["events"]) for h in d["holdings"] for c in h["viewed_by"]), "viewed-by matches the histories")
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

print("\n[4] same budget, other ways to choose")
for c in d["compare"]:
    print(f"    {c['name']:22} pieces {c['pieces']:2} spent ${c['spent']:>7,.0f} margin ${c['gross_margin']:>7,.0f} value ${c['value']:>8,.0f} "
          f"unplaced ${c['unplaced_capital']:>7,.0f}")
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

print("\n[6] the dealer's plan drives the numbers, the solver only suggests")
opening = [p["id"] for p in PIECES.values() if p["role"] == "lot"][:20]
empty = solve(budget=80_000, radar=opening)
check(empty["plan"]["picks"] == [] and empty["plan"]["value"] == 0 and empty["plan"]["spent"] == 0, "the plan starts empty and scores zero")
check(empty["next"] == empty["portfolio"], "with an empty plan, the next suggestion is the whole suggested plan")
suggested = empty["portfolio"]
use = solve(budget=80_000, radar=opening, plan=[x["lot"] for x in suggested["picks"]])
check(abs(use["plan"]["value"] - suggested["value"]) <= suggested["value"] * 0.005, "taking the whole suggestion scores what the solver said it would")
check(use["plan"]["spent"] == suggested["spent"] and use["plan"]["gross_margin"] == suggested["gross_margin"], "and costs the same")
check(use["portfolio"] == suggested, "the suggested plan doesn't depend on what the dealer picks")
some = [x["lot"] for x in suggested["picks"][:3]]
r = solve(budget=80_000, radar=opening, plan=some)
cost = sum(PIECES[l]["ask"] for l in some)
check(r["plan"]["spent"] == cost and r["plan"]["gross_margin"] == sum(PIECES[l]["resale"] - PIECES[l]["ask"] for l in some), "plan totals add up from its own lots")
check([x["lot"] for x in r["plan"]["picks"]] == some, "the plan holds exactly what the dealer chose")
check(not set(some) & {x["lot"] for x in r["next"]["picks"]}, "the next suggestion leaves out what is already planned")
check(r["next"]["spent"] <= 80_000 - cost, "the next suggestion fits the capital left")
by = defaultdict(int)
for x in r["plan"]["picks"] + r["next"]["picks"]:
    by[x["buyer"]] += 1
check(all(n <= 2 for b, n in by.items() if b), "plan and next together stay within each collector's slots")
trophy = max((PIECES[l] for l in opening), key=lambda p: p["ask"])
t = solve(budget=80_000, radar=opening, plan=[trophy["id"]])
pick = t["plan"]["picks"][0]
print(f"  {trophy['name']} (${trophy['ask']:,}) alone: buyer {pick['buyer']}, value ${t['plan']['value']:,.0f}, next {len(t['next']['picks'])} pieces, ${t['next']['spent']:,.0f}")
check(pick["buyer"] is not None or t["plan"]["value"] < 0, "a piece nobody can take is allowed and costs its holding charge")
over = solve(budget=20_000, radar=opening, plan=some + [trophy["id"]])
check(over["plan"]["spent"] > 20_000 and over["plan"]["unspent"] < 0, "going over capital is allowed and reported")
check(over["next"]["picks"] == [], "nothing more is suggested once over capital")
row = next(c for c in r["compare"] if c["key"] == "plan")
check(row["value"] == r["plan"]["value"] and row["pieces"] == 3, "the comparison table scores the plan the same way")
blocked = suggested["picks"][0]
b = solve(budget=80_000, radar=opening, plan=[blocked["lot"]], passes=[[blocked["lot"], blocked["buyer"]]])
check(b["plan"]["picks"][0]["buyer"] != blocked["buyer"], "a logged pass moves that piece to another collector")
check(client.post("/api/portfolio", json={"budget": 80_000, "plan": ["nope"]}).status_code == 422, "an unknown lot in a plan is refused")
print("\n[7] removed metrics")
check(all(k not in d for k in ("stress", "protection")) and all("worst_loss" not in c for c in d["compare"]), "no buyer-walks figures in the API")

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

print("\n[9] radar")
LOT_IDS = [p["id"] for p in PIECES.values() if p["role"] == "lot"]
base20 = LOT_IDS[:20]
r = solve(budget=80_000, radar=base20)
check(set(r["demand"]) == set(base20), "only lots on the radar get ranked")
check(all(d["rank"] <= 20 for rows in r["demand"].values() for d in rows), "ranks are among the 20 visible lots")
check({x["lot"] for x in r["portfolio"]["picks"]} <= set(base20), "the solver only buys from the radar")
r0 = solve(budget=0, radar=base20)
check(r0["portfolio"]["picks"] == [], "no capital left suggests nothing")
big = solve(budget=1_000_000)
check(big["portfolio"]["spent"] < 300_000, f"not forced to spend: ${big['portfolio']['spent']:,.0f} of $1,000,000")
check(all(x["value"] > -1 for x in big["portfolio"]["picks"]), "every suggested lot earns its place")

print("\n[10] buyer ties")
r = solve(budget=80_000, radar=base20)
p = r["portfolio"]
base_lots = sorted(x["lot"] for x in p["picks"])
print(f"    {len(p.get('ties', {}))} tied of {len(p['picks'])} suggested lots: {p.get('ties', {})}")
check("ties" in p and "ties" in r["plan"] and "ties" in r["next"], "ties are reported for the suggestion, the parcel and what's next")
for lot, others in p["ties"].items():
    pick = next(x for x in p["picks"] if x["lot"] == lot)
    rows = {d["collector"]: d for d in r["demand"][lot]}
    check(all(rows[c]["rank"] == pick["rank"] and rows[c]["affordable"] and not rows[c]["passed"] for c in others),
          f"{PIECES[lot]['name'][:34]}: tied buyers share the rank and are eligible")
    alt = solve(budget=80_000, radar=base20, passes=[[lot, pick["buyer"]]])["portfolio"]
    moved = next((x for x in alt["picks"] if x["lot"] == lot), None)
    check(sorted(x["lot"] for x in alt["picks"]) == base_lots and moved and moved["buyer"] in others and alt["value"] == p["value"],
          f"{PIECES[lot]['name'][:34]}: passing {pick['buyer']} moves it to a tied buyer, same lots, same value")
for x in p["picks"]:
    same = [d["collector"] for d in r["demand"][x["lot"]] if d["rank"] == x["rank"] and d["collector"] != x["buyer"] and d["affordable"]]
    for c in same:
        if c in p["ties"].get(x["lot"], []):
            continue
        alt = solve(budget=80_000, radar=base20, passes=[[x["lot"], x["buyer"]]])["portfolio"]
        check(alt["value"] < p["value"] or sorted(y["lot"] for y in alt["picks"]) != base_lots,
              f"{PIECES[x['lot']]['name'][:34]}: same rank as {c} but not a tie, and the swap does cost something")

print("\n[11] a tie goes to the buyer the dealer was shown, and nothing else moves")
tied_lot = next(iter(p["ties"]), None)  # live rankings can shift slightly, so a tie isn't guaranteed
if tied_lot is None:
    print("    no tie in the default book right now, skipping the tied-buyer checks")
else:
    first = next(x["buyer"] for x in p["picks"] if x["lot"] == tied_lot)
    other = p["ties"][tied_lot][0]
    def buyer_in_parcel(**kw):
        got = solve(budget=80_000, radar=base20, plan=[tied_lot], **kw)["plan"]
        return next(x["buyer"] for x in got["picks"] if x["lot"] == tied_lot), got["value"]
    a, value_a = buyer_in_parcel(prefer={tied_lot: first})
    b, value_b = buyer_in_parcel(prefer={tied_lot: other})
    check(a == first and b == other, f"either tied buyer can be kept ({first}, {other})")
    check(value_a == value_b, "keeping either buyer scores the same")
    c, _ = buyer_in_parcel(passes=[[tied_lot, first]], prefer={tied_lot: first})
    check(c == other, "a buyer who passed is not kept")
    d, _ = buyer_in_parcel(prefer={tied_lot: "nobody", "no-such-lot": first})
    check(d in (first, other), "unknown names in the preference are ignored")
# not a tie: a collector who ranks the lot lower, so asking for them changes nothing
lot, worse = next((x["lot"], d["collector"]) for x in p["picks"] for d in r["demand"][x["lot"]] if d["rank"] > x["rank"] and d["affordable"])
plain = solve(budget=80_000, radar=base20, plan=[lot])["plan"]
asked = solve(budget=80_000, radar=base20, plan=[lot], prefer={lot: worse})["plan"]
check(asked["picks"] == plain["picks"] and asked["value"] == plain["value"], f"asking for a lower-ranked buyer ({worse}) is ignored")
check(solve(budget=80_000, radar=base20, prefer={lot: worse})["portfolio"]["picks"] == p["picks"], "the suggestion itself does not read the preference")

print("\n[11] public-URL guards")
d = solve(budget=80_000, radar=base20)
check(d["meta"]["stopped_early"] is False, "no solve stopped at its time limit")
post = lambda **kw: client.post("/api/portfolio", json=kw).status_code
check(post(budget=80_000, radar=base20 + base20[:1]) == 422, "a lot listed twice is refused")
check(post(budget=80_000, radar=[base20[0]] * 65) == 422, "an oversized radar is refused")
check(post(budget=80_000, plan=[base20[0]] * 65) == 422, "an oversized plan is refused")
check(post(budget=80_000, passes=[[base20[0], "x"]] * 513) == 422, "an oversized pass list is refused")
check(client.post("/api/portfolio", content=b"x" * 128_001, headers={"content-type": "application/json"}).status_code == 413, "an oversized body is refused")

print("\nFAILURES:", failures)
sys.exit(1 if failures else 0)
