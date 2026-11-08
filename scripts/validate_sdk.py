"""What does BehaviorGPT actually do on a small jewelry catalog?

Histories here are hand-built test personas, so nothing below is evidence about
real collectors. It answers engineering questions: can we rank only a batch, do
rankings depend on the person and on event order, and what do scores look like.
"""
import json
import random
import statistics as st
import time
from pathlib import Path

from behaviorgpt import Order, Search, UnboxAIClient, View
from behaviorgpt._exceptions import UnboxAIError
from dotenv import load_dotenv
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
client = UnboxAIClient(market="us", timezone="America/New_York")
P = {p["id"]: p for p in json.loads((ROOT / "data/catalog/pieces.json").read_text())}
random.seed(7)


def pick(pred, n):
    hits = [p["id"] for p in P.values() if pred(p)]
    random.shuffle(hits)
    return hits[:n]


CLUSTERS = {
    "india_gems": lambda p: p["region"] == "India",
    "china_jade": lambda p: "Jade" in p["stones"],
    "renaissance_enamel": lambda p: p["period"] == "Renaissance & Baroque" and p["region"] in {"Italy", "Central Europe"},
    "antiquity_gold": lambda p: p["period"] == "Antiquity",
    "belle_epoque": lambda p: p["period"] == "Belle Epoque & Art Nouveau",
}
POOLS = {k: pick(v, 40) for k, v in CLUSTERS.items()}
print("cluster sizes", {k: len(v) for k, v in POOLS.items()})


def hist(ids):
    """Views with an order every third piece, oldest first."""
    events = []
    for i, x in enumerate(ids):
        events.append(View(x))
        if i % 3 == 2:
            events.append(Order([x]))
    return events


def rank_all(history, **kw):
    """Whole catalog ranking by paging: the fallback when no filter is used."""
    out, offset = [], 0
    while True:
        r = client.complete(history, limit=100, offset=offset, **kw)
        out.extend(r.items)
        if len(r.items) < 100:
            return out
        offset += 100


# 1 ---- ranking and filters
print("\n[1] whole-catalog ranking and filters")
t = time.time()
base = rank_all([])
print(f"  empty history: {len(base)} items ranked by paging in {time.time() - t:.2f}s")
batch = random.sample(list(P), 24)
for name, flt in [
    ("id $in", {"id": {"$in": batch}}),
    ("id $eq-list", {"id": batch}),
    ("categories", {"categories": "Brooch"}),
    ("brand", {"brand": "x"}),
]:
    try:
        r = client.complete([], limit=100, filters=flt)
        ok = {i.id for i in r.items}
        inb = len(ok & set(batch))
        print(f"  filter {name}: returned {len(ok)}, in batch {inb}")
    except UnboxAIError as e:
        print(f"  filter {name}: ERROR {e.status_code} {str(e)[:140]}")

# 2 ---- do rankings depend on the person?
print("\n[2] rankings per persona")
histories = {k: hist(v[:8]) for k, v in POOLS.items()}
ranks = {}
for k, h in histories.items():
    t = time.time()
    items = rank_all(h)
    ms = (time.time() - t) * 1000
    seen = set(POOLS[k][:8])
    ranks[k] = [i for i in items if i.id not in seen]
    top = ranks[k][:20]
    share = sum(CLUSTERS[k](P[i.id]) for i in top) / len(top)
    basert = sum(CLUSTERS[k](p) for p in P.values()) / len(P)
    sc = [i.score for i in ranks[k]]
    print(f"  {k}: top20 in-cluster {share:.0%} vs base {basert:.0%} | "
          f"score max {max(sc):.3f} med {st.median(sc):.3f} min {min(sc):.3f} | {ms:.0f}ms")
    print("     top5:", [P[i.id]["name"][:34] for i in top[:5]])

print("\n  pairwise spearman of full-catalog rankings")
keys = list(ranks)
common = set(P)
for k in keys:
    common &= {i.id for i in ranks[k]}
common = sorted(common)
order = {k: {i.id: n for n, i in enumerate(ranks[k])} for k in keys}
for a in range(len(keys)):
    print("  ", keys[a][:12].ljust(12), " ".join(
        f"{spearmanr([order[keys[a]][c] for c in common], [order[keys[b]][c] for c in common]).statistic:+.2f}"
        for b in range(len(keys))))

# 3 ---- does event order matter?
print("\n[3] sequence sensitivity: same events, different order")
a, b = POOLS["china_jade"][:6], POOLS["india_gems"][:6]
for title, seq1, seq2 in [("jade then india vs india then jade", a + b, b + a)]:
    r1 = [i for i in rank_all(hist(seq1)) if i.id not in set(a + b)]
    r2 = [i for i in rank_all(hist(seq2)) if i.id not in set(a + b)]
    for label, r in (("jade->india", r1), ("india->jade", r2)):
        top = r[:20]
        print(f"  {label}: top20 india {sum(CLUSTERS['india_gems'](P[i.id]) for i in top)}, "
              f"jade {sum(CLUSTERS['china_jade'](P[i.id]) for i in top)}")
    print(f"  top20 overlap {len({i.id for i in r1[:20]} & {i.id for i in r2[:20]})}/20")

# 4 ---- live signal: appended search
print("\n[4] live signal on one persona")
h = histories["belle_epoque"]
for label, ev in [("plain", []), ("+Search sapphire", [Search("sapphire")]),
                  ("+Search jade", [Search("jade")]), ("+View india piece", [View(POOLS["india_gems"][20])])]:
    t = time.time()
    r = client.complete(h + ev, limit=5)
    print(f"  {label}: {(time.time() - t) * 1000:.0f}ms", [P[i.id]["name"][:26] for i in r.items][:4])

# 5 ---- view vs purchase objective
print("\n[5] predict='view' vs predict='purchase'")
v = client.complete(histories["india_gems"], limit=20)
pu = client.complete(histories["india_gems"], limit=20, predict="purchase")
print("  top20 overlap", len({i.id for i in v.items} & {i.id for i in pu.items}))
print("  view scores", [round(i.score, 3) for i in v.items[:4]], "purchase", [round(i.score, 3) for i in pu.items[:4]])

# 6 ---- held-out next-pick, against a content-matching baseline
print("\n[6] held-out piece ranked within a 24-piece batch (synthetic personas)")


def feats(p):
    return {("f", p["form"]), ("p", p["period"]), ("r", p["region"]),
            *[("s", s) for s in p["stones"]], *[("m", m) for m in p["metals"]]}


def content_rank(hist_ids, cands):
    prof = {}
    for x in hist_ids:
        for f in feats(P[x]):
            prof[f] = prof.get(f, 0) + 1
    return sorted(cands, key=lambda c: -sum(prof.get(f, 0) for f in feats(P[c])))


res = {"bgpt": [], "content": [], "random": []}
agree = []
for k, pool in POOLS.items():
    for trial in range(8):
        ids = random.sample(pool, min(9, len(pool)))
        seen, target = ids[:-1], ids[-1]
        others = random.sample([x for x in P if x not in ids and not CLUSTERS[k](P[x])], 23)
        cands = others + [target]
        full = rank_all(hist(seen))
        rk = {i.id: n for n, i in enumerate(full)}
        b = sorted(cands, key=lambda c: rk.get(c, 999))
        c = content_rank(seen, cands)
        res["bgpt"].append(b.index(target) + 1)
        res["content"].append(c.index(target) + 1)
        res["random"].append(12.5)
        agree.append(spearmanr([b.index(x) for x in cands], [c.index(x) for x in cands]).statistic)
for m, v in res.items():
    print(f"  {m}: mean rank {st.mean(v):.1f} of 24, top3 {sum(x <= 3 for x in v) / len(v):.0%}")
print(f"  bgpt vs content ranking spearman: mean {st.mean(agree):+.2f}")
print("  note: clusters are defined by content, so this test favours the content baseline")
