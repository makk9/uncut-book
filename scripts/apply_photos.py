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
RAW2 = ROOT / "data" / "raw" / "candidates2"
THUMBS = ROOT / "data" / "raw" / "cma_thumbs"
PHOTOS = ROOT / "data" / "photos"
SHEETS = Path(sys.argv[1])
index = {x["n"]: x for x in json.loads((SHEETS / "sheets" / "index.json").read_text())}
index2 = {x["k"]: x for x in json.loads((SHEETS / "sheets2" / "index.json").read_text())}
museum = {x["m"]: x for x in json.loads((SHEETS / "cma" / "index.json").read_text())}

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
    ("m11", "Pink Tourmaline and Diamond Pendant Brooch, c. 1900", "Brooch", "Edwardian", "important", ["Tourmaline", "Diamond"], ["Platinum", "Gold"], 21000, 30500, "Belle Epoque scrolling diamond frame around a pink tourmaline with a matching drop"),
    ("m5", "Pearl and Diamond Spray Brooch, c. 1900", "Brooch", "Edwardian", "estate", ["Pearl", "Diamond"], ["Platinum", "Gold"], 8800, 13200, "Gold flower within a diamond crescent, hung with sprays of natural pearls"),
    ("m38", "Plique-a-Jour Dragonfly Brooch, c. 1905", "Brooch", "Edwardian", "unusual", ["Enamel"], ["Gold"], 6400, 11000, "Art Nouveau dragonfly with translucent plique-a-jour and cloisonne enamel wings"),
    ("m4", "Diamond and Pearl Lavalier Necklace, c. 1910", "Necklace", "Edwardian", "estate", ["Diamond", "Pearl"], ["Platinum", "Gold"], 16000, 23000, "Fine diamond-set links with a long kite-shaped pendant"),
]
HOLDINGS = [
    (229, "Diamond Ring Stack, Set of Four", "Ring", "Contemporary", "bridal", ["Diamond"], ["Platinum"], 7800, 10400, "Stacked diamond bands with emerald and marquise cuts"),
    (109, "Slim Gold Bangle Trio", "Bracelet", "Contemporary", "minimal", [], ["Gold"], 3100, 4200, "Three plain yellow gold bangles"),
    (66, "Antique Aquamarine Brooch and Earrings", "Brooch", "Edwardian", "estate", ["Aquamarine"], ["Gold"], 6400, 8800, "Matched set of round pale stones in openwork gold"),
    (59, "Antique Sapphire and Pearl Pendant", "Pendant", "Victorian", "estate", ["Sapphire", "Pearl"], ["Gold"], 4900, 7200, "Sapphire cluster pendant with a bow top and pearl drop"),
    (23, "Arts and Crafts Enamel Button, c. 1900", "Brooch", "Edwardian", "unusual", ["Enamel"], ["Silver"], 900, 1500, "Silver button with blue-green enamel and an orange cabochon"),
    (134, "Garnet Teardrop Pendant in Gold", "Pendant", "Antique", "unusual", ["Garnet"], ["Gold"], 2200, 3400, "Polished garnet teardrop in an early gold setting"),
]


# Past-purchase pieces, named from each photo and its source record. Asks are invented.
HISTORY = [
    # bridal
    (80, "Trio of Pave Diamond Rings", "Ring", "Contemporary", "bridal", ["Diamond"], ["Gold"], 9800, "Three yellow gold rings with pave diamond faces"),
    (98, "Cushion Sapphire and Diamond Engagement Ring", "Ring", "Contemporary", "bridal", ["Sapphire", "Diamond"], ["Platinum"], 11200, "Deep blue cushion sapphire with trillion diamond shoulders"),
    (99, "Parti Sapphire Three-Stone Engagement Ring", "Ring", "Contemporary", "bridal", ["Sapphire", "Diamond"], ["Gold"], 7400, "Oval Australian sapphire between small diamonds on a gold band"),
    (103, "Teal Sapphire Engagement Ring", "Ring", "Contemporary", "bridal", ["Sapphire", "Diamond"], ["Gold"], 6200, "Teal sapphire with kite-set diamonds on a slim gold band"),
    (102, "Pair of Green Sapphire Engagement Rings", "Ring", "Contemporary", "bridal", ["Sapphire", "Diamond"], ["Gold"], 8600, "Two bespoke green-blue sapphire rings"),
    (228, "White Gold Wedding Bands", "Ring", "Contemporary", "bridal", [], ["Gold"], 1900, "Matched white gold bands with a brushed finish"),
    # emerald
    (84, "Emerald and Diamond Ring", "Ring", "Contemporary", "statement", ["Emerald", "Diamond"], ["Gold"], 8200, "Square emerald with diamond clusters on a yellow gold band"),
    (85, "Wide Emerald Mosaic Band", "Ring", "Contemporary", "statement", ["Emerald"], ["Gold"], 5400, "Broad gold band with a lattice of small emeralds"),
    (82, "Oval Emerald Cabochon Ring", "Ring", "Contemporary", "classic", ["Emerald"], [], 3600, "Smooth oval emerald cabochon in a plain bezel"),
    (58, "Gold Heart Brooch with Emeralds", "Brooch", "Antique", "important", ["Emerald"], ["Gold"], 4400, "Domed gold heart pierced by a sword, set with emeralds"),
    ("m8", "Enameled Gold Pendant with Emerald, Late 1500s", "Pendant", "Renaissance", "important", ["Emerald", "Pearl"], ["Gold"], 12000, "Architectural enameled gold pendant with an emerald and hanging pearls"),
    ("m27", "Antique Emerald Ring in Silver", "Ring", "Georgian", "estate", ["Emerald"], ["Silver"], 1900, "Worn silver hoop with a square emerald, 1700s"),
    # sapphire
    (181, "Gold Sapphire Stacking Rings", "Ring", "Contemporary", "classic", ["Sapphire"], ["Gold"], 3200, "Three slim gold rings with pale sapphires"),
    (182, "Antique Sapphire Episcopal Ring", "Ring", "Antique", "important", ["Sapphire"], ["Gold"], 6400, "Large blue sapphire in an engraved gold ring"),
    (183, "Star Sapphire Men's Ring", "Ring", "Contemporary", "mens", ["Sapphire"], ["Gold"], 9800, "Very large round star sapphire cabochon, worn"),
    # art deco
    (19, "Art Deco Diamond Pendant Watch", "Pendant", "Art Deco", "estate", ["Diamond"], ["Platinum"], 14500, "Long geometric diamond pendant with a concealed watch"),
    (16, "Art Deco Enamel and Stone Buckle, 1925", "Brooch", "Art Deco", "estate", ["Enamel"], [], 3200, "Symmetrical scrolling buckle in lapis, coral and green enamel tones"),
    (21, "Molded Glass Parakeets Necklace", "Necklace", "Art Deco", "unusual", ["Glass"], [], 2400, "Frosted glass plaques on a cord, cast with parakeets"),
    (17, "Art Deco Glass Pendants on Silk", "Pendant", "Art Deco", "estate", ["Glass"], [], 1800, "Colored molded glass pendants on tasseled silk cords"),
    (22, "Molded Glass and Red Enamel Belt Buckle", "Brooch", "Art Deco", "unusual", ["Glass", "Enamel"], [], 1600, "Pale molded glass panel above a red and black enamel section"),
    # victorian and earlier estate
    (53, "Enameled Gold Link Bracelet, 1850-70", "Bracelet", "Victorian", "estate", ["Emerald"], ["Gold"], 3400, "Gold links with a central green stone"),
    (52, "Blue and White Enamel Bracelet with Pearls", "Bracelet", "Victorian", "estate", ["Pearl", "Diamond", "Enamel"], ["Gold"], 5200, "Dark blue enamel panels with pearl and diamond flowers"),
    ("m22", "Seed Pearl Parure, c. 1850", "Necklace", "Victorian", "estate", ["Pearl"], ["Gold"], 3800, "Necklace, pendant and earrings worked in seed pearls on mother-of-pearl"),
    ("m21", "Seed Pearl Drop Earrings, c. 1850", "Earrings", "Victorian", "estate", ["Pearl"], [], 1500, "Long drops of seed pearl balls on mother-of-pearl"),
    ("m14", "Seed Pearl Cluster Ring, Late 1800s", "Ring", "Victorian", "estate", ["Pearl"], ["Gold"], 1400, "Wide gold band crowded with seed pearls"),
    ("m52", "Garnet and Enamel Ring, c. 1860", "Ring", "Victorian", "estate", ["Garnet", "Enamel"], ["Gold"], 1100, "Pierced gold band with enamel scrolls"),
    ("m20", "Green Stone and Diamond Ring, c. 1870", "Ring", "Victorian", "unusual", ["Diamond"], ["Gold"], 2600, "Carved green stone head with diamond eyes in an engraved gold mount"),
    ("m53", "Cloisonne Enamel Gold Locket, 1868-70", "Pendant", "Victorian", "estate", ["Enamel"], ["Gold"], 1900, "Yellow enamel locket with plants and an insect"),
    ("m19", "Enameled Figure Pendant, 1870-90", "Pendant", "Victorian", "important", ["Pearl", "Enamel"], ["Gold"], 6200, "Two white enamel figures around a jeweled column"),
    # belle epoque and edwardian
    ("m2", "Diamond and Pearl Pendant Watch, c. 1900", "Pendant", "Edwardian", "estate", ["Diamond", "Pearl", "Ruby"], ["Platinum", "Gold"], 6800, "Pearl above a diamond and ruby ball that holds a watch"),
    ("m12", "Amethyst and Pearl Cross Necklace, c. 1905", "Necklace", "Edwardian", "estate", ["Amethyst", "Pearl"], ["Silver"], 1900, "Enameled silver chain and cross set with amethysts"),
    ("m13", "Aquamarine and Enamel Cloak Clasp, c. 1905", "Brooch", "Edwardian", "important", ["Aquamarine", "Pearl", "Enamel"], ["Gold"], 4800, "Two oyster enamel panels with aquamarines and half pearls"),
    ("m40", "Enamel and Citrine Pendant Brooch, c. 1905", "Brooch", "Edwardian", "estate", ["Citrine", "Enamel"], ["Gold"], 2200, "Green and orange enamel with hanging citrines"),
    ("m39", "Citrine and Blue Enamel Ring, c. 1910", "Ring", "Edwardian", "unusual", ["Citrine", "Enamel"], ["Gold"], 2100, "Large yellow stone in a pointed blue enamel mount"),
    ("m41", "Lily of the Valley Comb, c. 1900", "Hair Ornament", "Edwardian", "unusual", ["Pearl", "Enamel"], ["Gold"], 3600, "Carved horn comb with enameled flowers"),
    (206, "Arts and Crafts Diadem", "Tiara", "Edwardian", "important", ["Gemstones"], ["Gold"], 14000, "Gold headband with a central turquoise-toned stone and scrollwork"),
    (202, "Berlin Ironwork Tiara", "Tiara", "Victorian", "important", [], [], 9200, "Delicate black cast iron tiara of pierced palmettes"),
    # georgian and renaissance
    ("m0", "Multi-Gem Cluster Ring, 1700s", "Ring", "Georgian", "statement", ["Ruby", "Diamond", "Emerald", "Sapphire"], ["Gold", "Silver"], 3200, "Silver cluster of colored stones on a gold band"),
    ("m3", "Diamond and Enamel Cluster Ring, 1700s", "Ring", "Georgian", "estate", ["Diamond", "Enamel"], ["Gold", "Silver"], 2800, "Openwork silver and enamel cluster with diamonds"),
    ("m1", "Pelican Pendant with Rubies and Emeralds, c. 1600", "Pendant", "Renaissance", "important", ["Ruby", "Emerald", "Diamond", "Pearl"], ["Gold"], 28000, "Enameled gold pelican pendant hung with baroque pearls"),
    ("m7", "Enameled Gold Pendant with Rubies, 1600", "Pendant", "Renaissance", "important", ["Ruby", "Pearl"], ["Gold"], 9400, "Chained gold and enamel pendant with rubies and pearls"),
    # statement
    (177, "5 ct Princess Ruby Ring", "Ring", "Contemporary", "statement", ["Ruby"], ["Silver"], 18500, "Square ruby on a double band set with small rubies"),
    (176, "Burmese Ruby in a Silver Ring", "Ring", "Contemporary", "classic", ["Ruby"], ["Silver"], 2600, "Dark oval ruby in a plain silver ring"),
    (79, "Cognac Stone Cocktail Ring", "Ring", "Contemporary", "statement", ["Gemstones", "Diamond"], ["Gold"], 6600, "Orange-brown cushion stone in a large square of black and brown diamonds"),
    (150, "Pear Diamond Halo Pendant", "Pendant", "Contemporary", "line", ["Diamond"], ["Gold"], 5200, "Large pear-shaped diamond pendant in a pave halo"),
    # loose
    (4, "Pair of Alexandrites, Unset", "Loose stone", "Contemporary", "investment", ["Alexandrite"], [], 19000, "Two faceted cushion alexandrites showing a color change"),
    (48, "Old-Cut Diamond on a Display Pin", "Loose stone", "Antique", "investment", ["Diamond"], [], 12000, "Flat old-cut pale diamond shown unset"),
    (49, "Oval Old-Cut Diamond, Unset", "Loose stone", "Antique", "investment", ["Diamond"], [], 9200, "Pale yellow oval old-cut diamond"),
    (51, "Round Old-Cut Diamond, Unset", "Loose stone", "Antique", "investment", ["Diamond"], [], 7800, "Round old-cut diamond with a soft outline"),
    (207, "Large Faceted Topaz", "Loose stone", "Contemporary", "investment", ["Topaz"], [], 8800, "Very large cushion-cut pale blue topaz"),
    # minimal and pearl
    (157, "Pearl Drop Earrings, Three Pairs", "Earrings", "Contemporary", "minimal", ["Pearl"], ["Silver"], 1200, "Single cultured pearls on slim wires"),
    (163, "Cultured Pearl Strands", "Necklace", "Contemporary", "minimal", ["Pearl"], ["Gold"], 2100, "Loose white pearl strands with a gold clasp"),
    (223, "Gold Band with Channel Diamonds", "Ring", "Contemporary", "minimal", ["Diamond"], ["Gold"], 2200, "Plain gold band with a row of small diamonds"),
    (225, "Oxidized Wedding Bands", "Ring", "Contemporary", "minimal", [], ["Silver"], 1500, "Matte dark bands with tiny raised dots"),
    (149, "Wide White Gold Band", "Ring", "Contemporary", "minimal", [], ["Gold"], 1700, "Brushed 18k white gold ring with a grooved edge"),
    # watches and men's
    (232, "1970s Steel Diver's Watch", "Watch", "Mid-Century", "mens", [], ["Silver"], 900, "Steel case with a rotating bezel and brown dial"),
    (233, "1970s Steel Watch, Red Dial", "Watch", "Mid-Century", "mens", [], ["Silver"], 950, "Steel case with a rotating bezel and a red dial"),
    (231, "Mesh Strap Minimal Watch", "Watch", "Contemporary", "mens", [], ["Silver"], 700, "Rose-toned case with a disc dial on a mesh strap"),
    ("m6", "Gold and Pearl Pocket Watch, 1813", "Watch", "Georgian", "mens", ["Pearl", "Diamond", "Enamel"], ["Gold", "Silver"], 12000, "Engine-turned gold case rimmed with pearls"),
    ("m54", "Enameled Gilt Pocket Watch, Late 1700s", "Watch", "Georgian", "mens", ["Enamel"], ["Gold"], 5200, "Open case with painted enamel scenes"),
    (186, "Antique Seal Ring", "Ring", "Antique", "mens", [], ["Gold"], 3400, "Heavy cast ring with an engraved heraldic face"),
    # unusual
    (76, "Dendritic Agate Ring", "Ring", "Antique", "unusual", ["Agate"], ["Gold"], 1700, "Pale agate with dark inclusions in a pearl-beaded surround"),
    (209, "Silver Plaid Brooch with a Citrine", "Brooch", "Victorian", "unusual", ["Citrine"], ["Silver"], 900, "Round engraved Scottish-style silver brooch"),
    ("m36", "Silver Filigree Chain with Turquoise Cross", "Chain", "Victorian", "unusual", ["Turquoise"], ["Silver"], 1200, "Long fine silver chain with a filigree cross"),
    ("m37", "Painted Enamel Band", "Ring", "Victorian", "unusual", ["Enamel"], ["Silver"], 800, "Wide silver ring with painted blue and green flowers"),
    (65, "Silver Hoop Pendant with Old-Cut Diamonds", "Pendant", "Antique", "unusual", ["Diamond"], ["Silver"], 1600, "Open silver circle set with small old-cut diamonds"),
]


# Modern retail-style pieces. Skipped on purpose: identifiable people, branded promo shots,
# famous named jewels (a replica royal ring, a ring made for a public figure) and black opals.
HISTORY2 = [
    ("k55", "Round Lab-Grown Diamond Halo Ring", "Ring", "Contemporary", "bridal", ["Diamond"], ["Platinum"], 6400, "Round center in a pave halo on a slim band"),
    ("k56", "Blue Princess Cut Solitaire", "Ring", "Contemporary", "bridal", ["Diamond"], ["Platinum"], 5400, "Square blue stone in a simple four-prong mount"),
    ("k57", "Emerald-Cut Diamond and Alexandrite Engagement Ring", "Ring", "Contemporary", "bridal", ["Diamond", "Alexandrite"], ["Gold"], 13500, "Step-cut diamond with round alexandrite side stones"),
    ("k72", "Group of Five Diamond Engagement Rings", "Ring", "Contemporary", "bridal", ["Diamond"], ["Platinum"], 16000, "White metal solitaires with pave shoulders"),
    ("k80", "Parti Sapphire and Diamond Rose Gold Ring", "Ring", "Contemporary", "bridal", ["Sapphire", "Diamond"], ["Gold"], 6800, "Oval teal sapphire between diamond clusters"),
    ("k90", "Yellow Sapphire and Diamond Engagement Ring", "Ring", "Contemporary", "bridal", ["Sapphire", "Diamond"], ["Gold"], 4900, "Square yellow sapphire with channel-set diamonds in 18k gold"),
    ("k93", "Pear Cut Parti Sapphire Solitaire", "Ring", "Contemporary", "bridal", ["Sapphire"], ["Gold"], 4200, "Pear sapphire on a plain yellow gold band"),
    ("k92", "Pair of Plain Gold Engagement Bands", "Ring", "Contemporary", "bridal", [], ["Gold"], 1200, "Two grooved yellow gold bands"),
    ("k60", "Bezel-Set Ruby and Diamond Eternity Band", "Ring", "Contemporary", "line", ["Ruby", "Diamond"], ["Gold"], 2800, "Marquise rubies and round diamonds around a gold band"),
    ("k81", "Plain 18k Domed Gold Ring", "Ring", "Contemporary", "minimal", [], ["Gold"], 1400, "Polished domed yellow gold band"),
    ("k158", "Gold Ring with Scattered Diamonds", "Ring", "Contemporary", "minimal", ["Diamond"], ["Gold"], 1800, "Rose gold band set with tiny diamonds"),
    ("k52", "Open Gold Ring with Bezel Diamonds", "Ring", "Contemporary", "minimal", ["Diamond"], ["Gold"], 2400, "Airy yellow gold ring with small bezel-set diamonds"),
    ("k165", "Bezel-Set Moonstone Ring", "Ring", "Contemporary", "minimal", ["Moonstone"], ["Gold"], 1100, "Domed moonstone in a yellow gold bezel"),
    ("k140", "Fine Gold Necklace with Diamond Bar", "Necklace", "Contemporary", "minimal", ["Diamond"], ["Gold"], 1100, "Hair-thin gold chain with a small diamond cluster"),
    ("k47", "Blue Sapphire and Diamond Necklace", "Necklace", "Contemporary", "statement", ["Sapphire", "Diamond"], ["Platinum"], 24000, "Graduated clusters of blue sapphires framed in diamonds"),
    ("k28", "Rough Diamond Necklace", "Necklace", "Contemporary", "unusual", ["Diamond"], ["Gold"], 6800, "Several strands of natural rough diamond beads"),
    ("k30", "Lapis Lazuli Necklace with Diamonds", "Necklace", "Contemporary", "unusual", ["Lapis", "Diamond", "Sapphire"], ["Gold"], 5200, "Lapis beads and a large lapis drop set with small stones"),
    ("k36", "Kundan Necklace with an Emerald Drop", "Necklace", "Antique", "important", ["Diamond", "Emerald", "Pearl"], ["Gold"], 18000, "Indian kundan collar in gold with pearls and an emerald drop"),
    ("k122", "Antique Indian Gold Necklace and Earrings", "Necklace", "Victorian", "estate", [], ["Gold"], 9000, "Layered panels of worked gold with matching earrings"),
    ("k138", "Pair of Heavy 22k Gold Necklaces", "Necklace", "Contemporary", "street", [], ["Gold"], 12800, "Dense high-karat gold collars shown on displays"),
    ("k124", "Twisted Gold Rope Necklace", "Chain", "Contemporary", "street", ["Diamond"], ["Gold"], 9200, "Soft gold rope with a pave diamond station"),
    ("k39", "Long Openwork Link Chain", "Chain", "Edwardian", "estate", [], ["Silver"], 2400, "Dark metal chain of pierced openwork links"),
    ("k135", "Gold Openwork Collar", "Necklace", "Edwardian", "important", [], ["Gold"], 5200, "Rigid collar of intertwined gold stems"),
    ("k106", "Art Deco Link Bracelet, 1925", "Bracelet", "Art Deco", "estate", ["Gemstones"], ["Gold"], 7800, "Rectangular worked gold panels divided by small stones"),
    ("k9", "White Gold and Diamond Drop Earrings", "Earrings", "Contemporary", "statement", ["Diamond"], ["Gold"], 7400, "Long drops of large round and pear diamonds"),
    ("k17", "White Gold Bezel Drop Earrings", "Earrings", "Contemporary", "minimal", ["Diamond"], ["Gold"], 1100, "Small bezel-set stones on white gold wires"),
    ("k24", "Emerald and Diamond Star Earrings", "Earrings", "Contemporary", "statement", ["Emerald", "Diamond"], ["Gold"], 7200, "Diamond stars above pear emerald drops"),
    ("k25", "Pearl and Diamond Tassel Earrings", "Earrings", "Contemporary", "statement", ["Pearl", "Diamond"], ["Gold"], 11000, "White pearls above articulated diamond tassels"),
    ("k20", "Carved Jade Basket Earrings", "Earrings", "Contemporary", "unusual", ["Jade", "Diamond"], ["Gold"], 8200, "Green carved jade in diamond hoops with a jade drop"),
    ("k68", "Pave Diamond Square Gold Ring", "Ring", "Contemporary", "mens", ["Diamond"], ["Gold"], 5600, "Heavy square-faced yellow gold ring with a pave top"),
    ("k69", "Black Onyx and Diamond Gold Ring", "Ring", "Contemporary", "mens", ["Onyx", "Diamond"], ["Gold"], 2300, "Diagonal black onyx panel in a broad gold band"),
    ("k157", "Engraved Gold Trophy Ring", "Ring", "Contemporary", "mens", [], ["Gold"], 1200, "Heavy yellow gold award ring"),
    ("k61", "Group of Cut and Rough Diamonds", "Loose stone", "Contemporary", "investment", ["Diamond"], [], 22000, "Several unset diamonds, rough and faceted"),
]


def entry(row: tuple) -> dict:
    n, name, form, era, style, stones, metals, ask, resale, description = row
    return {"name": name, "form": form, "era": era, "style": style, "stones": stones, "metals": metals,
            "ask": ask, "resale": resale, "description": description, "photo": slug(n)}


def slug(ref) -> str:
    return ref if isinstance(ref, str) else f"p{ref:03d}"


def hist_entry(row: tuple) -> dict:
    n, name, form, era, style, stones, metals, ask, description = row
    return entry((n, name, form, era, style, stones, metals, ask, None, description))


def record(ref) -> tuple[Path, dict]:
    """The file and credit for a photo: Commons candidate, or Cleveland CC0 record."""
    if isinstance(ref, str) and ref.startswith("k"):
        src = index2[ref]
        return RAW2 / f"{src['cid']}.jpg", commons_credit(src)
    if isinstance(ref, str):
        m = museum[int(ref[1:])]
        return THUMBS / f"cma{m['id']}.jpg", {
            "title": f"{m['title']} ({m['date']})", "author": "Cleveland Museum of Art", "license": "CC0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "source": "Cleveland Museum of Art Open Access", "landing_url": m["url"],
        }
    src = index[ref]
    return RAW / f"{src['cid']}.jpg", commons_credit(src)


def commons_credit(src: dict) -> dict:
    license_ok = src["license"].lower() in ("cc0", "public domain")
    assert (src["author"] or "").strip() or license_ok, f"{src['title']} has no author to credit"
    credit = {k: src[k] for k in ("title", "author", "license", "license_url", "source", "landing_url")}
    credit["author"] = (credit["author"] or "").strip() or "Unknown"
    return credit


PHOTOS.mkdir(parents=True, exist_ok=True)
credits = {}
rows = LOTS + HOLDINGS + HISTORY + HISTORY2
assert len({r[0] for r in rows}) == len(rows), "a photo is used twice"
for row in rows:
    path, credit = record(row[0])
    shutil.copy(path, PHOTOS / f"{slug(row[0])}.jpg")
    credits[slug(row[0])] = credit
(PHOTOS / "credits.json").write_text(json.dumps(credits, indent=1, ensure_ascii=False))

path = ROOT / "data" / "book" / "curated.json"
curated = json.loads(path.read_text())
curated["lot"] = [entry(r) for r in LOTS]
curated["holding"] = [entry(r) for r in HOLDINGS]
curated["history"] = [hist_entry(r) for r in HISTORY + HISTORY2]
path.write_text(json.dumps(curated, indent=1, ensure_ascii=False))
from collections import Counter
print("pieces", len(rows), Counter(c["license"].split()[0].lower() + (" " + c["license"].split()[1].lower() if len(c["license"].split()) > 1 and c["license"].startswith("CC") else "") for c in credits.values()).most_common())
for k in ("form", "style", "era"):
    print(k, Counter(r[{"form": 2, "style": 4, "era": 3}[k]] for r in HISTORY + HISTORY2).most_common())
