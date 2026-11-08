"""Attach reviewed, licensed photos to the lots and holdings in data/book/curated.json.

Each choice was checked by eye and against its source record, so lot names and
descriptions below say what the photo shows. Copies the files to data/photos/ with
their credits. The lots themselves stay fictional, and their prices are invented.
Run once with the path to the contact sheet index.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "candidates"
PHOTOS = ROOT / "data" / "photos"
index = {x["n"]: x for x in json.loads(Path(sys.argv[1]).read_text())}

LOTS = [
    (77, "Round Diamond Halo Engagement Ring", "Ring", "Contemporary", "bridal", ["Diamond"], ["Gold"], 28000, 36500, "Round brilliant center in a pave halo on a split white gold band"),
    (55, "Asymmetrical Platinum Diamond Bracelet", "Bracelet", "Art Deco", "estate", ["Diamond"], ["Platinum"], 9500, 14800, "Geometric open links set with round and baguette diamonds"),
    (104, "Ceylon Sapphire and Diamond Ring", "Ring", "Contemporary", "statement", ["Sapphire", "Diamond"], ["Gold"], 34000, 46000, "Oval vivid blue Ceylon sapphire with diamond shoulders in yellow gold"),
    (83, "5.42 ct Colombian Emerald and Trillion Ring", "Ring", "Contemporary", "statement", ["Emerald", "Diamond"], ["Platinum"], 19000, 26000, "Colombian emerald between trillion cut diamonds, platinum and gold mount"),
    (108, "18k Gold Diamond Tennis Bracelet", "Bracelet", "Contemporary", "line", ["Diamond"], ["Gold"], 14500, 19800, "Round diamonds set in a yellow gold line bracelet with a box clasp"),
    (70, "Cabochon Emerald and Diamond Necklace", "Necklace", "Contemporary", "statement", ["Emerald", "Diamond"], ["Platinum"], 52000, 68000, "Large polished emerald cabochon on an open diamond link necklace"),
    (175, "Ruby and Diamond Cocktail Ring", "Ring", "Contemporary", "statement", ["Ruby", "Diamond"], ["Gold"], 62000, 86000, "Large oval pinkish-red ruby in a scalloped diamond and baguette surround"),
    (106, "22k Gold Patterned Bangles, Set of Four", "Bracelet", "Contemporary", "street", [], ["Gold"], 11500, 14600, "Heavy high-karat yellow gold bangles with a repeating pattern"),
    (40, "Beatrice Cenci Cameo Brooch, c. 1850", "Brooch", "Victorian", "estate", ["Cameo"], ["Gold"], 1800, 3200, "Carved shell cameo portrait in a gold serpent frame"),
    (57, "Emerald Paste Spray Brooch, c. 1760", "Brooch", "Georgian", "important", ["Gemstones"], ["Silver"], 6800, 10200, "Period colored paste set in silver, a floral spray with a drop"),
    (205, "Sapphire and Gold Diadem, c. 1890", "Tiara", "Victorian", "important", ["Sapphire"], ["Gold"], 38000, 54000, "Gold scrollwork diadem set with blue stones, shown on a velvet form"),
    (161, "Akoya Pearl Double Strand", "Necklace", "Contemporary", "minimal", ["Pearl"], ["Gold"], 7200, 10400, "Two long matched strands of white akoya pearls"),
    (61, "Antique Sapphire and Diamond Drop Earrings", "Earrings", "Victorian", "estate", ["Sapphire", "Diamond", "Pearl"], ["Gold"], 13800, 19000, "Articulated clusters of blue sapphires and rose cut diamonds with pearl tips"),
    (230, "Pair of 18k Gold Wedding Bands", "Ring", "Contemporary", "minimal", [], ["Gold"], 1600, 2600, "Plain polished yellow gold bands"),
    (50, "Old-Cut Golconda-Type Diamond, Unset", "Loose stone", "Antique", "investment", ["Diamond"], [], 17500, 21500, "Flat old-cut pale yellow diamond shown on a display pin"),
    (81, "Paraiba Tourmaline and Diamond Ring", "Ring", "Contemporary", "unusual", ["Tourmaline", "Diamond"], ["Platinum"], 16000, 24500, "Oval neon blue paraiba tourmaline in a pear diamond surround"),
    (179, "Star Sapphire Ring, Silver Mount", "Ring", "Mid-Century", "unusual", ["Sapphire"], ["Silver"], 5400, 8900, "Domed purple star sapphire cabochon in a heavy brushed mount"),
    (238, "1961 Gold-Plated Square Dress Watch", "Watch", "Mid-Century", "mens", [], ["Gold"], 1800, 2900, "Cushion-case mechanical dress watch on a black leather strap"),
    (190, "Gold Intaglio Signet Ring", "Ring", "Contemporary", "mens", [], ["Gold"], 2400, 3900, "Square-faced yellow gold signet with a hand-cut palm device"),
    (64, "Aquamarine and Diamond Drop Earrings", "Earrings", "Contemporary", "statement", ["Aquamarine", "Diamond"], ["Gold"], 6800, 10200, "Pear aquamarines hanging from pave diamond discs"),
]
HOLDINGS = [
    (229, "Diamond Ring Stack, Set of Four", "Ring", "Contemporary", "bridal", ["Diamond"], ["Platinum"], 7800, 10400, "Stacked diamond bands with emerald and marquise cuts"),
    (109, "Slim Gold Bangle Trio", "Bracelet", "Contemporary", "minimal", [], ["Gold"], 3100, 4200, "Three plain yellow gold bangles"),
    (66, "Antique Aquamarine Brooch and Earrings", "Brooch", "Edwardian", "estate", ["Aquamarine"], ["Gold"], 6400, 8800, "Matched set of round pale stones in openwork gold"),
    (59, "Antique Sapphire and Pearl Pendant", "Pendant", "Victorian", "estate", ["Sapphire", "Pearl"], ["Gold"], 4900, 7200, "Sapphire cluster pendant with a bow top and pearl drop"),
    (23, "Arts and Crafts Enamel Button, c. 1900", "Brooch", "Edwardian", "unusual", ["Enamel"], ["Silver"], 900, 1500, "Silver button with blue-green enamel and an orange cabochon"),
    (134, "Garnet Teardrop Pendant in Gold", "Pendant", "Antique", "unusual", ["Garnet"], ["Gold"], 2200, 3400, "Polished garnet teardrop in an early gold setting"),
]


def entry(row: tuple) -> dict:
    n, name, form, era, style, stones, metals, ask, resale, description = row
    return {"name": name, "form": form, "era": era, "style": style, "stones": stones, "metals": metals,
            "ask": ask, "resale": resale, "description": description, "photo": f"p{n:03d}"}


PHOTOS.mkdir(parents=True, exist_ok=True)
credits = {}
for row in LOTS + HOLDINGS:
    n = row[0]
    src = index[n]
    assert (src["author"] or "").strip(), f"#{n} has no author to credit"
    shutil.copy(RAW / f"{src['cid']}.jpg", PHOTOS / f"p{n:03d}.jpg")
    credits[f"p{n:03d}"] = {k: src[k] for k in ("title", "author", "license", "license_url", "source", "landing_url")}
    print(n, src["license"], "|", src["title"][:50], "|", src["author"][:26], "->", row[1][:40])
(PHOTOS / "credits.json").write_text(json.dumps(credits, indent=1, ensure_ascii=False))

path = ROOT / "data" / "book" / "curated.json"
curated = json.loads(path.read_text())
curated["lot"] = [entry(r) for r in LOTS]
curated["holding"] = [entry(r) for r in HOLDINGS]
path.write_text(json.dumps(curated, indent=1, ensure_ascii=False))
