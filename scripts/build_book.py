"""Build the demo book from data/book/curated.json (hand-reviewed photos and lot text).

Everything here is representative demo data: the people, their events, asks and
resale estimates are invented, and the app says so. Histories are simulated from
persona tastes with a fixed seed. No BehaviorGPT output is written here, so the
rankings the app shows later are the model's, not this script's.
"""
import hashlib
import json
import random
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from behaviorgpt.resources.catalogs import CATALOG_SCHEMA, check_catalog_schema

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "data" / "book"
IMAGES = ROOT / "data" / "images"
STONE_COLOR = {
    "Diamond": "#cfe6ee", "Sapphire": "#3d6fd6", "Ruby": "#c92f4d", "Emerald": "#2fae74", "Pearl": "#e8dfcd",
    "Opal": "#9bd6c8", "Tourmaline": "#2fc3bb", "Aquamarine": "#7fc8e0", "Amethyst": "#8a5fc7",
    "Turquoise": "#3bb6b0", "Cameo": "#d8a98c", "Gemstones": "#b5a3c9",
}
PHOTOS = ROOT / "data" / "photos"
REPO_RAW = "https://raw.githubusercontent.com/makk9/uncut-book/main/data/photos"
METAL_COLOR = {"Gold": "#d9a93f", "Platinum": "#b9c1c4", "Silver": "#a7adb0"}
rng = random.Random(11)

# Each phase: (taste weights, sessions, what they ask about). Later phases are more recent.
PERSONAS = [
    ("rachel", "Rachel Stein", "Great Neck, NY", "Buys bridal for three generations of family friends. Round and oval diamonds, nothing loud.",
     [({"form:Ring": 2, "style:bridal": 5, "stone:Diamond": 4, "metal:Platinum": 2}, 9, ["diamond engagement ring", "oval diamond ring", "platinum solitaire"])]),
    ("marcus", "Marcus Bell", "Queens, NY", "Started with heavy gold chains. The last year of browsing has moved to diamond line pieces.",
     [({"form:Chain": 6, "metal:Gold": 4, "style:street": 5, "form:Pendant": 2}, 6, ["gold chain", "cuban link", "gold pendant"]),
      ({"form:Bracelet": 5, "stone:Diamond": 5, "style:line": 5, "form:Necklace": 2}, 5, ["tennis bracelet", "diamond line necklace"])]),
    ("ines", "Ines Duarte", "Miami, FL", "Colored stones only. Bought emerald for years, and recent calls have all been about sapphire.",
     [({"stone:Emerald": 7, "style:statement": 2, "form:Ring": 2}, 6, ["emerald ring", "colombian emerald"]),
      ({"stone:Sapphire": 7, "style:statement": 2, "form:Ring": 2, "form:Loose stone": 2}, 4, ["sapphire ring", "blue sapphire"])]),
    ("julian", "Julian Hale", "Upper East Side, NY", "Estate purist. Art Deco platinum first, and will pay for period and condition.",
     [({"era:Art Deco": 8, "metal:Platinum": 3, "style:estate": 4, "stone:Diamond": 2}, 9, ["art deco ring", "art deco brooch", "platinum filigree"])]),
    ("theo", "Theo Laurent", "Palm Beach, FL", "Wants the room to notice. Cocktail rings and big center stones, gets bored quickly.",
     [({"style:statement": 8, "form:Ring": 4, "stone:Ruby": 2, "stone:Sapphire": 2, "stone:Emerald": 2}, 8, ["cocktail ring", "large statement ring"])]),
    ("naomi", "Naomi Katz", "Brooklyn, NY", "Careful buyer on a modest budget. Victorian brooches, cameos and lockets.",
     [({"era:Victorian": 8, "form:Brooch": 5, "form:Pendant": 2, "style:estate": 3, "stone:Cameo": 5}, 8, ["victorian brooch", "cameo", "antique locket"])]),
    ("dev", "Dev Rao", "Hoboken, NJ", "Treats stones as a store of value. Loose goods, rarely anything set.",
     [({"form:Loose stone": 9, "stone:Diamond": 3, "stone:Sapphire": 2, "stone:Ruby": 2, "style:investment": 4}, 8, ["loose diamond", "loose sapphire", "unset ruby"])]),
    ("claudia", "Claudia Moretti", "Tribeca, NY", "Quiet modern taste. Pearls and clean gold she can wear every day.",
     [({"style:minimal": 7, "stone:Pearl": 4, "metal:Gold": 3, "form:Earrings": 3}, 8, ["pearl earrings", "gold hoops", "pearl strand"])]),
    ("andre", "Andre Whitfield", "Atlanta, GA", "Men's pieces. Watches and chains, and increasingly signet rings.",
     [({"form:Watch": 7, "form:Chain": 4, "metal:Gold": 3}, 6, ["gold watch", "gold chain"]),
      ({"style:mens": 6, "form:Ring": 4, "metal:Gold": 3, "form:Watch": 3}, 3, ["signet ring", "mens gold ring"])]),
    ("sofia", "Sofia Alvarez", "Scottsdale, AZ", "Follows unusual stones. Opal, turquoise and anything she has not seen before.",
     [({"stone:Opal": 7, "stone:Turquoise": 6, "stone:Aquamarine": 3, "stone:Amethyst": 3, "style:unusual": 5}, 8, ["opal ring", "turquoise jewelry", "unusual gemstone"])]),
    ("daniel", "Daniel Cho", "Fort Lee, NJ", "Bought loose diamonds for years. Has lately been asking about period settings to put them in.",
     [({"form:Loose stone": 7, "stone:Diamond": 6, "style:investment": 3}, 6, ["loose diamond", "certified diamond"]),
      ({"era:Art Deco": 6, "era:Edwardian": 4, "style:estate": 4, "stone:Diamond": 3}, 4, ["art deco setting", "edwardian ring"])]),
    ("margot", "Margot Ellery", "Boston, MA", "Museum-minded. Tiaras, important brooches and pieces with a story, at her own pace.",
     [({"form:Tiara": 8, "form:Brooch": 5, "era:Edwardian": 3, "era:Victorian": 3, "style:important": 6}, 8, ["tiara", "important antique brooch"])]),
]


def tags(p: dict) -> set[str]:
    return {f"form:{p['form']}", f"era:{p['era']}", f"style:{p['style']}",
            *[f"stone:{s}" for s in p["stones"]], *[f"metal:{m}" for m in p["metals"]]}


def affinity(weights: dict, p: dict) -> float:
    return 0.05 + sum(weights.get(t, 0) for t in tags(p))


def weighted_sample(pool: list[dict], weights: dict, k: int) -> list[dict]:
    pool = list(pool)
    out = []
    for _ in range(min(k, len(pool))):
        w = [affinity(weights, p) ** 2 for p in pool]
        x = rng.choices(pool, weights=w)[0]
        pool.remove(x)
        out.append(x)
    return out


ID_PREFIX = {"lot": "lot", "holding": "inv", "history": "his"}


def placeholder_svg(p: dict) -> str:
    """Temporary art: a faceted stone in the piece's real color. Labeled, never passed off as a photo."""
    color = STONE_COLOR.get((p["stones"] or [""])[0]) or METAL_COLOR.get((p["metals"] or [""])[0], "#888")
    seed = int(hashlib.sha1(p["id"].encode()).hexdigest()[:6], 16)
    n = 6 + seed % 4
    import math
    outer = [(160 + 74 * math.cos(2 * math.pi * i / n), 108 + 66 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    inner = [(160 + 34 * math.cos(2 * math.pi * (i + .5) / n), 108 + 30 * math.sin(2 * math.pi * (i + .5) / n)) for i in range(n)]
    facets = ""
    for i in range(n):
        a, b, c = outer[i], outer[(i + 1) % n], inner[i]
        op = 0.25 + 0.6 * (((seed >> i) & 3) / 3)
        facets += f'<polygon points="{a[0]:.0f},{a[1]:.0f} {b[0]:.0f},{b[1]:.0f} {c[0]:.0f},{c[1]:.0f}" fill="{color}" fill-opacity="{op:.2f}"/>'
    core = " ".join(f"{x:.0f},{y:.0f}" for x, y in inner)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 240"><rect width="320" height="240" fill="#0b0e0d"/>'
            f'<ellipse cx="160" cy="108" rx="112" ry="90" fill="{color}" fill-opacity=".09"/>{facets}'
            f'<polygon points="{core}" fill="{color}" fill-opacity=".95"/>'
            f'<text x="160" y="212" text-anchor="middle" font-family="monospace" font-size="11" fill="#6f7773">{p["form"].upper()} · PHOTO PENDING</text></svg>')


def main() -> None:
    curated = json.loads((BOOK / "curated.json").read_text())
    credits = json.loads((PHOTOS / "credits.json").read_text())
    IMAGES.mkdir(parents=True, exist_ok=True)
    for old in list(IMAGES.glob("*.svg")) + list(IMAGES.glob("*.jpg")):
        old.unlink()

    pieces, lot_no = [], 0
    for role in ("lot", "holding", "history"):
        for n, row in enumerate(curated[role]):
            pid = f"{ID_PREFIX[role]}{n:03d}"
            lot_no += role == "lot"
            ask = row["ask"]
            piece = {
                "id": pid, "role": role, "lot_no": lot_no if role == "lot" else None,
                "name": row["name"], "form": row["form"], "era": row["era"], "style": row["style"],
                "stones": row.get("stones", []), "metals": row.get("metals", []),
                "description": row.get("description", ""),
                "ask": ask, "resale": row.get("resale", round(ask * 1.3, -2)),
                "image": f"/img/{pid}.svg", "image_url": None, "credit": None,
            }
            if row.get("photo"):
                # image_url must stay fetchable by Unbox's servers: a public repo serves it
                shutil.copy(PHOTOS / f"{row['photo']}.jpg", IMAGES / f"{pid}.jpg")
                piece["image"] = f"/img/{pid}.jpg"
                piece["image_url"] = f"{REPO_RAW}/{row['photo']}.jpg"
                piece["credit"] = credits[row["photo"]]
            else:
                (IMAGES / f"{pid}.svg").write_text(placeholder_svg(piece))
            pieces.append(piece)

    # the server keys pieces by id and the catalog keeps the first row of a duplicate id
    assert len({p["id"] for p in pieces}) == len(pieces), "piece ids must be unique"

    history_pool = [p for p in pieces if p["role"] == "history"]
    available = {p["id"]: p for p in history_pool}
    collectors = []
    for pid, name, city, blurb, phases in PERSONAS:
        events, spent = [], []
        for weights, sessions, queries in phases:
            for _ in range(sessions):
                if rng.random() < 0.6:
                    events.append({"type": "search", "q": rng.choice(queries)})
                viewed = weighted_sample(history_pool, weights, rng.randint(2, 4))
                events += [{"type": "view", "id": v["id"]} for v in viewed]
                if rng.random() < 0.4:
                    # one of a kind: a piece bought by someone is gone
                    open_ = [v for v in viewed if v["id"] in available]
                    if open_:
                        buy = max(open_, key=lambda v: affinity(weights, v))
                        del available[buy["id"]]
                        events.append({"type": "order", "id": buy["id"]})
                        spent.append(buy["resale"])
        last_three = sum(spent[-3:])
        cap = max(max(spent, default=0) * 1.5, last_three)
        cap = float(round(cap, -3))
        collectors.append({
            "id": pid, "name": name, "city": city, "blurb": blurb, "events": events, "capacity": cap,
            "capacity_note": f"Capacity is computed, not stated: the larger of 1.5× their largest past purchase and their last three purchases combined. Purchases are invented.",
            "lifetime_spend": sum(spent), "orders": len(spent),
        })

    def row(p):
        return {
            "id": p["id"], "name": f"{p['name']}. {p['description']}".strip(" ."),
            "brand": None,
            "categories": ", ".join(["Jewelry", p["form"], p["era"], *p["stones"], *p["metals"]]),
            "image_url": p["image_url"], "event_type": "product", "group": "product",
            "sales_since": None, "timestamp": None, "frequency": None, "market": None,
            "price": str(p["ask"]), "currency": "USD", "search_keywords": None, "keywords": None,
        }

    out = ROOT / "data" / "catalog" / "the_book_catalog.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([row(p) for p in pieces], schema=pa.schema(CATALOG_SCHEMA)), out)
    check_catalog_schema(out)
    (BOOK / "pieces.json").write_text(json.dumps(pieces, indent=1, ensure_ascii=False))
    (BOOK / "collectors.json").write_text(json.dumps(collectors, indent=1, ensure_ascii=False))

    lines = ["# Photo credits", "",
             "These photos stand in for fictional lots. Lot names, asks and resale figures are invented and say nothing about the pictured objects or their owners. Copies here are resized. Other pieces use placeholder art made for this project.", "",
             "| File | Source title | Author | License | Source |", "|---|---|---|---|---|"]
    for pid, c in sorted(credits.items()):
        title, author = (c["title"].replace("|", " "), c["author"].replace("|", " ").replace("\n", " "))
        lines.append(f"| {pid}.jpg | {title} | {author} | [{c['license']}]({c['license_url']}) | [{c['source']}]({c['landing_url']}) |")
    (ROOT / "CREDITS.md").write_text("\n".join(lines) + "\n")

    (BOOK / "rankings_snapshot.json").unlink(missing_ok=True)  # ids changed, old rankings no longer apply

    print("pieces", {r: sum(p["role"] == r for p in pieces) for r in ("lot", "holding", "history")})
    for c in collectors:
        print(f"  {c['name']:18} events {len(c['events']):3} orders {c['orders']:2} spend {c['lifetime_spend']:>9,.0f} capacity {c['capacity']:>9,.0f}")


main()
