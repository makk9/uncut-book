"""Pull real, CC0 jewelry records from the Cleveland Museum of Art Open Access API.

Output: data/raw/cma_jewelry.json. Nothing here is a market fact: these objects
stand in for estate lots in a demo. Prices, collectors and events are invented
elsewhere and labelled as such.
"""
import json
from pathlib import Path

import httpx

URL = "https://openaccess-api.clevelandart.org/api/artworks/"
OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "cma_jewelry.json"
FIELDS = (
    "id,accession_number,title,creation_date,creation_date_earliest,"
    "creation_date_latest,culture,technique,type,department,creators,images,url,"
    "tombstone,description"
)
PAGE = 200

rows: list[dict] = []
with httpx.Client(timeout=60, follow_redirects=True) as c:
    skip = 0
    while True:
        r = c.get(URL, params={"type": "Jewelry", "has_image": 1, "cc0": 1,
                               "limit": PAGE, "skip": skip, "fields": FIELDS})
        r.raise_for_status()
        page = r.json()["data"]
        rows.extend(page)
        print(f"fetched {len(rows)}", flush=True)
        if len(page) < PAGE:
            break
        skip += PAGE

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(rows, indent=1))
print("DONE", len(rows))
