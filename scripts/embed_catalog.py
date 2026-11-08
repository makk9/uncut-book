"""Upload data/catalog/the_book_catalog.parquet and record its catalog id in .env.

The file name is the catalog's name, so re-running refreshes the same slot.
"""
import re
import time
from pathlib import Path

from behaviorgpt import UnboxAIClient
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
load_dotenv(ENV)

client = UnboxAIClient(market="us")
started = time.time()
job = client.embed(
    ROOT / "data" / "catalog" / "the_book_catalog.parquet", wait=True, timeout=1500.0
)
print(f"ready in {time.time() - started:.0f}s: {job.catalog_id}")
text = ENV.read_text()
line = f"UNBOXAI_CATALOG_ID={job.catalog_id}"
text = (
    re.sub(r"^UNBOXAI_CATALOG_ID=.*$", line, text, flags=re.M)
    if re.search(r"^UNBOXAI_CATALOG_ID=", text, flags=re.M)
    else text.rstrip() + "\n" + line + "\n"
)
ENV.write_text(text)
