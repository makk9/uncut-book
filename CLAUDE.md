# THE BOOK

Jewelry trading and acquisition terminal for independent estate-jewelry dealers. Sundai hack that ships today.

Demo sentence: "This dealer has $80,000 to spend. THE BOOK helps them figure out which stones are worth chasing, and who might want them."

Flow: collector book -> incoming lots -> behavioral matching -> optimized portfolio -> dealer decision. Holdings and sourcing only support this flow. Out of scope: CRM, marketplace, transactions, auto-purchasing.

## Honesty rules (non-negotiable)

- BehaviorGPT scores are not probabilities and never enter money math. Use rank within the batch only.
- No fabricated sale probabilities, no valuations presented as market fact, no profitability claims.
- Don't claim BehaviorGPT beats tag matching. Our test: mean rank 4.9 vs 1.3 of 24, on synthetic personas that favored tags; correlation between the two +0.25. Say what it does differently: reads new pieces from photo and text with no tagging, and tracks order of events.
- All collectors, prices and events are invented, and the UI must say so.
- `entity_prob` appears in item data but is undocumented. Don't use it.
- Never stage a result. If the trophy-vs-portfolio contrast doesn't emerge from real rankings, say so; don't fake scores to get it.

## BehaviorGPT

Reference: https://portal.unboxai.com/llms.txt and the docs it links. Use them; don't guess the API.

Verified by running it (some of this differs from the README):
- `retail_catalog` is unknown; the shared catalog is `retail_catalog_500k`.
- The `price` column does not affect rankings: stripping it left them almost unchanged (tested on 129 pieces). The README and format doc disagree; the format doc is right.
- Glamorous multi-gem lots rank well for nearly everyone, so raw rank piles the book onto them. `relative` in `server/app.py` corrects this using ranks only. Don't remove it without re-checking `scripts/validate_book.py`.
- Rank a batch with `filters={"id": [...]}`. `$in` returns 422. `limit` max is 100.
- Scores sit around 1.18-1.43 regardless of collector.
- Recency dominates: the same events reversed share only 3 of the top 20.
- Embedding 300 items took 17s; a re-rank takes about 160-220ms.
- 2 catalog slots per key. Re-uploading the same file name refreshes the slot, so keep the name `the_book_catalog`.
- Keep popularity columns (`sales_since`, `timestamp`, `frequency`) null: one-of-a-kind pieces have no sales history.
- Pass market and timezone only, not gender or age. Rankings should read only what the collector did.

## Architecture decisions

- Two lenses per collector: full sequence and orders-only, blended by a recency weight. This guards against one stray view moving a $60k decision. The gap between lenses is the taste-drift signal.
- Lot selection and buyer assignment are one MILP (SciPy HiGHS), so overlapping demand on a collector is handled directly by capacity and slot constraints.
- Fit comes from rank with an explicit decay; value = fit x dealer's margin estimate, minus a holding penalty for missing fit. All knobs stay visible in the UI.
- Resilience mode and the buyer-walks stress test measure single-collector dependence.
- Comparison strategies (trophy, paper margin, tag matching) are scored under the same rules as THE BOOK, and the UI labels that scoring as THE BOOK's assumptions.
- Dealer inventory is every piece nobody bought: the 6 curated holdings plus unsold history pieces. `build_book.py` assigns those roles after drawing histories, so ids stay `his###` and catalog rows don't change. Inventory is ranked only against itself and doesn't affect the solver.
- Demo moment: log a signal ("called about sapphires"), re-rank live, portfolio changes.
- `rankings_snapshot.json` is the fallback if the API fails during the demo. The UI must show live vs snapshot.

## Paths

- `server/optimizer.py`: MILP, stress test, frontier, comparison strategies
- `server/rankings.py`: BehaviorGPT calls, lenses, cache, snapshot
- `server/app.py`: API; also serves `data/images/` and `web/dist/`
- `scripts/build_book.py`: builds the simulated book from `data/book/curated.json`; `scripts/embed_catalog.py` uploads it; `scripts/check_e2e.py` checks a running server
- `data/book/`: `curated.json` (source), `pieces.json`, `collectors.json`, `rankings_snapshot.json` (generated). Rebuilding deletes the snapshot, because ids may change
- `data/photos/`: reviewed photos with `credits.json`; `data/images/`: what the app serves (copies plus placeholder art)
- `web/`: React + Vite terminal UI
- `data/raw/` is gitignored working data; never publish from it directly
- `scripts/validate_sdk.py` and `scripts/build_catalog.py` are the early validation on Cleveland museum records. They don't run against the current catalog

Repo: github.com/makk9/uncut-book (public). Catalog image URLs point at its `main` branch, so push photos before embedding.

## Data and images

- Allowed licenses: CC0, public domain, CC BY, CC BY-SA. Record author, license and source for every image, and credit them in the app and repo.
- No people or identifiable faces. Review images by eye before use; source metadata is unreliable.
- Don't imply real brand listings. Don't attach a maker's name to invented lots and prices.
- Catalog text must be truthful to the image, because it goes into the embedding. Wrong labels degrade rankings.
- Images are re-hosted in the public repo so Unbox's servers can fetch them. Test with a plain server fetch.
- Respect bot protection. The Met API blocked our script and we did not work around it. Back off when a host rate-limits.

## Visual identity

Dark charcoal, emerald, amber; dense professional trading terminal with rich gemstone photography. Inspired by the atmosphere of a film about Diamond District dealers, but use no characters, names, or plot items from it. It must read as real software, not a game. Footer must say "Built at Sundai".

## Commands

```bash
uv sync
uv run python scripts/build_book.py
uv run python scripts/embed_catalog.py
uv run uvicorn server.app:app --reload
cd web && npm install && npm run dev
uv run python scripts/check_e2e.py
```

The server loads `data/book/` at import, so restart it after a rebuild. Docker's `--env-file` keeps quotes that python-dotenv strips, and a quoted key fails as "Invalid API key". Pass the key without quotes on any host.

## Secrets

`UNBOXAI_API_KEY` and `UNBOXAI_CATALOG_ID` live only in gitignored `.env`. Never print, commit, or paste the key, and keep it server-side. Check for secrets before every push.

## Sundai launch checklist

- Working deployed URL (off localhost)
- Public GitHub repo
- sundai.club/projects post with 30s video
- Attribution to Sundai
- Live user testing at launch
