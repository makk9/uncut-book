"""Numbered contact sheets of the candidate photos, for reviewing them by eye."""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
COLS, ROWS, TILE = 8, 5, 170
rows = json.loads((RAW / "candidates.json").read_text())
rows.sort(key=lambda x: (x["bucket"], x["cid"]))
index = []
for s in range(0, len(rows), COLS * ROWS):
    sheet = Image.new("RGB", (COLS * TILE, ROWS * TILE), "#111")
    draw = ImageDraw.Draw(sheet)
    for n, x in enumerate(rows[s : s + COLS * ROWS]):
        num = s + n
        index.append({"n": num, **x})
        with Image.open(RAW / "candidates" / f"{x['cid']}.jpg") as im:
            im.thumbnail((TILE - 4, TILE - 4))
            sheet.paste(im, ((n % COLS) * TILE + 2, (n // COLS) * TILE + 2))
        cx, cy = (n % COLS) * TILE + 2, (n // COLS) * TILE + 2
        draw.rectangle((cx, cy, cx + 30, cy + 13), fill="#000")
        draw.text((cx + 2, cy + 1), str(num), fill="#ffd257")
    sheet.save(OUT / f"sheet_{s // (COLS * ROWS):02d}.jpg", quality=80)
(OUT / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False))
print(len(rows), "images,", (len(rows) + COLS * ROWS - 1) // (COLS * ROWS), "sheets")
