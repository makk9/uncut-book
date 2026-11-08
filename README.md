# THE BOOK

Know your buyers. Own the right stones.

An acquisition terminal for independent jewelry dealers. Given a budget, a book of collectors and a batch of incoming lots, it proposes which lots to buy and who each one is for. It uses real BehaviorGPT rankings and a capital-constrained optimizer.

**All data is simulated.** Collectors, events, asks and resale estimates are invented. The rankings are real BehaviorGPT output on those histories. Fit comes from rank order and is not a probability of sale.

## How it works

1. Each collector's history goes to [BehaviorGPT](https://github.com/Unbox-AI/behaviorgpt), which ranks the batch. Two lenses are used: the full sequence, and purchases only.
2. A MILP (SciPy HiGHS) chooses lots and assigns each to one collector together, under the budget, each collector's capacity and a limit on pieces per collector. A lot two collectors want can only go to one of them, and one collector cannot absorb everything.
3. A stress test removes each buyer in turn and re-places the portfolio.

## Run it

Get a free key at [portal.unboxai.com](https://portal.unboxai.com), then put `UNBOXAI_API_KEY` in `.env`.

```bash
uv sync
```

```bash
uv run python scripts/build_book.py
```

```bash
uv run python scripts/embed_catalog.py
```

```bash
uv run uvicorn server.app:app --reload
```

```bash
cd web && npm install && npm run dev
```

Built at [Sundai](https://www.sundai.club/).
