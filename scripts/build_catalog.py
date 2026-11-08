"""Turn the raw Cleveland records into a BehaviorGPT catalog parquet.

Every column comes from the museum record. No prices or popularity numbers are
written: one-of-a-kind pieces have no sales history, and the docs say null means
"all items rank as equally popular", which is the truthful input here.
"""
import json
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from behaviorgpt.resources.catalogs import CATALOG_SCHEMA, check_catalog_schema

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "cma_jewelry.json"
OUT = ROOT / "data" / "catalog" / "the_book_catalog.parquet"
META = ROOT / "data" / "catalog" / "pieces.json"
TARGET = 300

FORMS = [
    ("Tiara", r"tiara|diadem"), ("Brooch", r"brooch|fibula|\bpin\b"),
    ("Necklace", r"necklace|choker|collar|torque"), ("Pendant", r"pendant|locket|amulet"),
    ("Earrings", r"earring|ear ornament"), ("Bracelet", r"bracelet|bangle|armlet|cuff"),
    ("Ring", r"\brings?\b"), ("Clasp", r"clasp|buckle"), ("Hair Ornament", r"comb|hair"),
]
STONES = [
    ("Diamond", r"diamond"), ("Emerald", r"emerald"), ("Ruby", r"rub(y|ies)"),
    ("Sapphire", r"sapphire"), ("Pearl", r"pearl"), ("Opal", r"opal"),
    ("Garnet", r"garnet"), ("Amethyst", r"amethyst"), ("Turquoise", r"turquoise"),
    ("Jade", r"jade|nephrite"), ("Enamel", r"enamel"), ("Carnelian", r"carnelian"),
    ("Gemstones", r"\bjewels?\b|precious|semi-?precious|gemstones?|\bstones?\b"),
]
METALS = [("Gold", r"\bgold\b"), ("Silver", r"silver"), ("Platinum", r"platinum")]


def period(year: int) -> str:
    if year < 500:
        return "Antiquity"
    if year < 1500:
        return "Medieval"
    if year < 1700:
        return "Renaissance & Baroque"
    if year < 1837:
        return "Georgian Era"
    if year < 1890:
        return "Victorian Era"
    if year < 1920:
        return "Belle Epoque & Art Nouveau"
    if year < 1945:
        return "Art Deco & Retro"
    return "Modern"


def region(culture: str) -> str:
    c = culture.lower()
    pairs = [
        ("India", "india|mughal|deccan"), ("Himalaya", "nepal|tibet"),
        ("Central Europe", "hungar|transylvan|austria|german|bohemia"),
        ("France", "france|french"), ("Italy", "ital|venice|etruscan|roman"),
        ("Britain", "england|british|scotland|ireland"), ("America", "america|united states"),
        ("China", "china"), ("Southeast Asia", "burma|thai|java|indonesia|cambodia"),
        ("Egypt", "egypt"), ("West Africa", "ghana|asante|ivoire|baule|mali|senegal"),
        ("Andes", "peru|colombia|ecuador|muisca"), ("Islamic World", "iran|persia|turk|ottoman|syria"),
    ]
    for name, pat in pairs:
        if re.search(pat, c):
            return name
    return "Other"


def tagged(table, text):
    return [name for name, pat in table if re.search(pat, text, re.I)]


def score(p: dict) -> tuple:
    """Prefer jewels a dealer could plausibly handle: stones first, then recency."""
    gem = sum(s in {"Diamond", "Emerald", "Ruby", "Sapphire", "Pearl", "Opal"} for s in p["stones"])
    return (gem, len(p["stones"]), p["year"] >= 1500, p["year"])


pieces = []
for o in json.loads(RAW.read_text()):
    title, tech = o.get("title") or "", o.get("technique") or ""
    web = ((o.get("images") or {}).get("web") or {}).get("url")
    if not web or re.search(r"fragment|\bbeads?\b|spacer|unknown", title, re.I):
        continue
    forms = tagged(FORMS, title)
    if not forms:
        continue
    year = int(o.get("creation_date_latest") or 0)
    culture = (o.get("culture") or ["Unattributed"])[0]
    western = region(culture) in {"France", "Italy", "Britain", "America", "Central Europe"}
    era = period(year) if western or year < 500 else f"{year // 100 + 1}th century"
    creators = o.get("creators") or []
    maker = (creators[0].get("description") or "").split("(")[0].strip() if creators else ""
    pieces.append({
        "id": f"cma{o['id']}",
        "name": title.strip(),
        "form": forms[0],
        "stones": tagged(STONES, tech),
        "metals": tagged(METALS, tech),
        "year": year,
        "date": o.get("creation_date") or "",
        "period": era,
        "region": region(culture),
        "culture": culture,
        "maker": maker,
        "technique": tech,
        "image": web,
        "source": o.get("url"),
        "accession": o.get("accession_number"),
    })

pieces = sorted(pieces, key=score, reverse=True)[:TARGET]

rows = []
for p in pieces:
    material = p["stones"] + p["metals"]
    rows.append({
        "id": p["id"],
        "name": f"{p['name']} ({p['technique']})" if p["technique"] else p["name"],
        "brand": p["maker"] or None,
        "categories": ", ".join(["Jewelry", p["form"], p["period"], p["region"], *material]),
        "image_url": p["image"],
        "event_type": "product",
        "group": "product",
        "sales_since": None, "timestamp": None, "frequency": None,
        "market": None, "price": None, "currency": None,
        "search_keywords": None, "keywords": None,
    })

OUT.parent.mkdir(parents=True, exist_ok=True)
pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(CATALOG_SCHEMA)), OUT)
check_catalog_schema(OUT)
META.write_text(json.dumps(pieces, indent=1, ensure_ascii=False))

from collections import Counter
print("items", len(rows))
for key in ("form", "period", "region"):
    print(key, Counter(p[key] for p in pieces).most_common())
print("stones", Counter(s for p in pieces for s in p["stones"]).most_common())
print("makers", sum(1 for p in pieces if p["maker"]))
