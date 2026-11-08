"""Gather candidate jewelry photos from Wikimedia Commons and Openverse.

Only CC0, public-domain, CC BY and CC BY-SA files are kept, with their author and
source page, so every image used can be credited. Downloads land in
data/raw/candidates/ (gitignored) for review; nothing is published from here.
"""
import asyncio
import hashlib
import html
import io
import json
import re
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
IMG = RAW / "candidates"
IMG.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "TheBook/0.1 (Sundai hackathon demo; https://www.sundai.club/) httpx"}
PER_CATEGORY = 8  # a small, bounded set: this runs in the background and blocks nothing

COMMONS = [
    "Diamond rings", "Engagement rings", "Art Deco jewellery", "Gold rings", "Gold necklaces",
    "Diamond necklaces", "Pearl necklaces", "Gold bracelets", "Diamond bracelets",
    "Diamond earrings", "Gold earrings", "Pearl earrings", "Brooches", "Diamond brooches",
    "Tiaras", "Cameos", "Sapphire rings", "Emerald rings", "Ruby rings", "Cut diamonds",
    "Faceted gemstones", "Sapphires", "Rubies", "Emeralds", "Opals", "Tanzanite", "Alexandrite",
    "Aquamarine", "Tourmaline", "Topaz", "Amethyst", "Garnets", "Jewellery by Cartier",
    "Jewellery by Tiffany & Co.", "Victorian jewellery", "Edwardian jewellery",
    "Art Nouveau jewellery", "Signet rings", "Wedding rings", "Gold chains", "Wristwatches",
    "Gold jewellery", "Pendants", "Lockets", "Jewellery in the Green Vault",
]
OPENVERSE = [
    "diamond engagement ring", "solitaire diamond ring", "halo diamond ring", "emerald cut diamond ring",
    "tennis bracelet", "diamond bracelet", "gold bangle bracelet", "gold chain necklace", "cuban link chain",
    "diamond necklace", "pearl strand necklace", "diamond stud earrings", "gold hoop earrings",
    "chandelier earrings", "sapphire ring", "ruby ring", "emerald ring", "loose gemstones", "loose diamond",
    "art deco ring", "art deco brooch", "victorian brooch", "estate jewelry", "vintage cocktail ring",
    "gold signet ring", "gold wristwatch", "opal ring", "sapphire necklace", "gold pendant",
]
SKIP = re.compile(r"\b(portrait|painting|wearing|queen|princess|king|actress|model|logo|icon|map|diagram|"
                  r"drawing|engraving|sketch|statue|tattoo|wedding day|bride|groom|flower)\b", re.I)


async def polite_get(c: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    """Back off when a host says it is busy, as its Retry-After asks."""
    r = httpx.Response(599)
    for attempt in range(4):
        try:
            r = await c.get(url, **kw)
        except httpx.HTTPError as exc:
            print("retry", type(exc).__name__, url[:80], flush=True)
            r = httpx.Response(599)
            await asyncio.sleep(3 * (attempt + 1))
            continue
        if r.status_code not in (429, 502, 503, 504):
            return r
        await asyncio.sleep(float(r.headers.get("retry-after") or 0) or 5 * (attempt + 1))
    return r


def clean(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def commons_license(short: str) -> str | None:
    s = (short or "").lower()
    if s in {"cc0", "public domain", "pd", "pdm"} or s.startswith("public domain"):
        return "public domain" if "cc0" not in s else "cc0"
    if re.fullmatch(r"cc by \d\.\d", s) or s == "cc by":
        return s.upper()
    if re.fullmatch(r"cc by-sa \d\.\d", s) or s == "cc by-sa":
        return s.upper()
    return None


async def commons(c: httpx.AsyncClient) -> list[dict]:
    out = []
    for cat in COMMONS:
        r = await polite_get(c, "https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "generator": "categorymembers",
            "gcmtitle": f"Category:{cat}", "gcmtype": "file", "gcmlimit": 30,
            "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 800,
        })
        if r.status_code != 200:
            print("commons", cat, r.status_code, flush=True)
            continue
        pages = (r.json().get("query") or {}).get("pages") or {}
        n = 0
        for p in pages.values():
            info = (p.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            lic = commons_license((meta.get("LicenseShortName") or {}).get("value", ""))
            if not lic or info.get("mime") not in {"image/jpeg", "image/png"}:
                continue
            if min(info.get("width", 0), info.get("height", 0)) < 500:
                continue
            if n >= PER_CATEGORY:
                break
            title = p["title"].removeprefix("File:").rsplit(".", 1)[0]
            out.append({
                "source": "Wikimedia Commons", "bucket": cat, "title": title, "license": lic,
                "license_url": (meta.get("LicenseUrl") or {}).get("value", ""),
                "author": clean((meta.get("Artist") or {}).get("value", ""))[:120],
                "landing_url": info.get("descriptionurl"), "image_url": info.get("thumburl") or info.get("url"),
            })
            n += 1
        print(f"commons {cat}: {len(pages)} files, {n} usable", flush=True)
        await asyncio.sleep(1.5)
    return out


async def openverse(c: httpx.AsyncClient) -> list[dict]:
    out = []
    for q in OPENVERSE:
        r = await polite_get(c, "https://api.openverse.org/v1/images/", params={
            "q": q, "license": "cc0,pdm,by,by-sa", "page_size": 20, "mature": "false"})
        if r.status_code != 200:
            print("openverse", q, r.status_code, flush=True)
            await asyncio.sleep(5)
            continue
        rows = r.json().get("results", [])
        for x in rows:
            if (x.get("width") or 999) < 500 and (x.get("height") or 999) < 500:
                continue
            out.append({
                "source": f"{x['source'].title()} via Openverse", "bucket": q, "title": x["title"],
                "license": x["license"].upper() + (" " + x["license_version"] if x.get("license_version") else ""),
                "license_url": x.get("license_url", ""), "author": (x.get("creator") or "")[:120],
                "landing_url": x.get("foreign_landing_url"), "image_url": x["url"],
            })
        print(f"openverse {q}: {len(rows)}", flush=True)
        await asyncio.sleep(13)  # anonymous limit is 5 requests a minute
    return out


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, headers=UA, follow_redirects=True) as c:
        manifest = RAW / "candidates_manifest.json"
        if manifest.exists():
            rows = json.loads(manifest.read_text())
        else:
            rows = await commons(c)  # Openverse left out: it was timing out and blocking the build
            manifest.write_text(json.dumps(rows))
        seen, unique = set(), []
        for x in rows:
            if x["image_url"] in seen or SKIP.search(x["title"]):
                continue
            seen.add(x["image_url"])
            x["cid"] = hashlib.sha1(x["image_url"].encode()).hexdigest()[:12]
            unique.append(x)
        print("candidates", len(unique), flush=True)

        sem = asyncio.Semaphore(2)
        kept = []

        async def grab(x):
            path = IMG / f"{x['cid']}.jpg"
            if path.exists():
                with Image.open(path) as im:
                    x["w"], x["h"] = im.size
                kept.append(x)
                return
            async with sem:
                try:
                    r = await polite_get(c, x["image_url"])
                    r.raise_for_status()
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                except Exception as e:
                    print("skip", x["cid"], type(e).__name__, flush=True)
                    return
                if min(im.size) < 400:
                    return
                im.thumbnail((800, 800))
                im.save(path, quality=85)
                x["w"], x["h"] = im.size
                kept.append(x)
                await asyncio.sleep(0.5)

        await asyncio.gather(*(grab(x) for x in unique))
    (RAW / "candidates.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False))
    from collections import Counter
    print("DONE kept", len(kept), Counter(x["license"] for x in kept).most_common(8))
    print(Counter(x["source"] for x in kept).most_common())


asyncio.run(main())
