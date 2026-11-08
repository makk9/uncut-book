"""Does mixing photo lots with text-only history hurt collector matches?

Uploads a text-only copy of the book under its own file name, so it takes the second
catalog slot and leaves the main catalog and .env untouched. Then ranks the same batch
for the same collectors in both catalogs and compares them.

The personas are invented and their tastes are written in tags, so the taste score
favors whatever matches tags. Use it to compare the two catalogs, not as evidence
about real collectors.
"""
import json
import os
import statistics as st
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from behaviorgpt import Order, Search, UnboxAIClient, View
from behaviorgpt.resources.catalogs import CATALOG_SCHEMA, check_catalog_schema
from dotenv import load_dotenv
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
load_dotenv(ROOT / ".env")

from build_book import PERSONAS, affinity  # noqa: E402
from server import optimizer as opt  # noqa: E402

BOOK = ROOT / "data" / "book"
P = {p["id"]: p for p in json.loads((BOOK / "pieces.json").read_text())}
COLLECTORS = json.loads((BOOK / "collectors.json").read_text())
LOTS = [p for p in P.values() if p["role"] == "lot"]
LOT_IDS = [p["id"] for p in LOTS]
MAIN = os.environ["UNBOXAI_CATALOG_ID"]
client = UnboxAIClient(market="us", timezone="America/New_York")


def stamp(catalog_id: str) -> str:
    return client._http_client.get(f"/catalogs/{catalog_id}/stats").json()["updated_at"]


def upload_text_only() -> str:
    rows = pq.read_table(ROOT / "data/catalog/the_book_catalog.parquet").to_pylist()
    for r in rows:
        r["image_url"] = None
    path = ROOT / "data/catalog/the_book_text_only.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(CATALOG_SCHEMA)), path)
    check_catalog_schema(path)
    job = client.embed(path, wait=True, timeout=600.0, on_progress=lambda _: None)
    return job.catalog_id


def events(rows):
    out = []
    for e in rows:
        if e["type"] == "search":
            out.append(Search(e["q"]))
        elif e["type"] == "view":
            out.append(View(e["id"]))
        else:
            out.append(Order([e["id"]]))
    return out


def rank(rows, catalog_id):
    r = client.complete(events(rows), limit=100, filters={"id": LOT_IDS}, catalog_id=catalog_id, register_event=False)
    order = [i.id for i in r.items]
    return order + [x for x in LOT_IDS if x not in order]


def blended(c, catalog_id, recency=0.6):
    full = {x: n + 1 for n, x in enumerate(rank(c["events"], catalog_id))}
    bought = [e for e in c["events"] if e["type"] == "order"]
    orders = {x: n + 1 for n, x in enumerate(rank(bought, catalog_id))}
    return sorted(LOT_IDS, key=lambda x: (recency * full[x] + (1 - recency) * orders[x], full[x]))


def taste(pid):
    """Each persona's taste by phase. Later phases are the current taste."""
    phases = next(p[4] for p in PERSONAS if p[0] == pid)
    return phases[-1][0]


before = stamp(MAIN)
existing = {c.catalog_name: c.catalog_id for c in client.list_catalogs() if c.owned}
print("owned before:", existing)
test_id = upload_text_only()
print("text-only catalog:", test_id)
assert test_id != MAIN, "the test must not land on the main catalog"
assert stamp(MAIN) == before, "the main catalog changed"
print("main catalog unchanged, updated_at", before)

arms = {"photos (current)": MAIN, "text-only": test_id}
orders = {a: {c["id"]: blended(c, cid) for c in COLLECTORS} for a, cid in arms.items()}

print("\n[1] top 3 per collector")
for c in COLLECTORS:
    print(f"\n  {c['name']}: {c['blurb'][:74]}")
    for a in arms:
        print(f"    {a:17}", " | ".join(P[x]["name"][:30] for x in orders[a][c["id"]][:3]))

print("\n[2] agreement with each persona's current taste (spearman, higher is closer)")
scores = {a: [] for a in arms}
top3 = {a: [] for a in arms}
for c in COLLECTORS:
    w = taste(c["id"])
    aff = [affinity(w, P[x]) for x in LOT_IDS]
    best = sorted(aff, reverse=True)[:3]
    for a in arms:
        pos = [orders[a][c["id"]].index(x) for x in LOT_IDS]
        scores[a].append(-spearmanr(pos, aff).statistic)
        top3[a].append(sum(affinity(w, P[x]) for x in orders[a][c["id"]][:3]) / max(sum(best), 1e-9))
for a in arms:
    print(f"  {a:17} mean {st.mean(scores[a]):+.2f} median {st.median(scores[a]):+.2f} | top-3 taste captured {st.mean(top3[a]):.0%}")
diff = [x - y for x, y in zip(scores["text-only"], scores["photos (current)"])]
print(f"  text-only better for {sum(d > 0 for d in diff)} of {len(diff)} collectors; mean difference {st.mean(diff):+.2f}")
for c, d in sorted(zip(COLLECTORS, diff), key=lambda x: x[1]):
    print(f"    {c['name']:18} {d:+.2f}")

print("\n[3] how much do collectors differ?")
for a in arms:
    firsts = [orders[a][c["id"]][0] for c in COLLECTORS]
    counts = {x: firsts.count(x) for x in set(firsts)}
    worst = max(counts, key=counts.get)
    pairs = []
    for i, x in enumerate(COLLECTORS):
        for y in COLLECTORS[i + 1:]:
            ox = {k: n for n, k in enumerate(orders[a][x["id"]])}
            oy = {k: n for n, k in enumerate(orders[a][y["id"]])}
            pairs.append(spearmanr([ox[k] for k in LOT_IDS], [oy[k] for k in LOT_IDS]).statistic)
    print(f"  {a:17} {len(counts)} distinct #1 lots; most common: {P[worst]['name'][:32]} ({counts[worst]} of {len(firsts)}); "
          f"mean collector-to-collector correlation {st.mean(pairs):+.2f}")

print("\n[4] the portfolio each would propose at $80k")
lots = [{"id": l["id"], "ask": l["ask"], "resale": l["resale"]} for l in LOTS]
buyers = [{"id": c["id"], "capacity": c["capacity"]} for c in COLLECTORS]
name = {c["id"]: c["name"] for c in COLLECTORS}
for a in arms:
    ranks = np.array([[orders[a][c["id"]].index(l) + 1 for c in COLLECTORS] for l in LOT_IDS], float)
    r = opt.solve(opt.Problem(lots, buyers, ranks), opt.Params(budget=80_000))
    print(f"\n  {a}: {len(r['picks'])} pieces, spent ${r['spent']:,.0f}, value ${r['value']:,.0f}")
    for x in r["picks"]:
        print(f"    {P[x['lot']]['name'][:42]:42} -> {name[x['buyer']]:16} #{x['rank']}")
print("\nmain catalog still unchanged:", stamp(MAIN) == before)
