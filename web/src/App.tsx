import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

type Credit = { title: string; author: string; license: string; license_url: string; source: string; landing_url: string };
type Piece = {
  id: string; lot_no: number; name: string; form: string; era: string; style: string; stones: string[]; metals: string[];
  ask: number; resale: number; image: string; description: string; credit: Credit | null;
};
type TimelineEvent = { type: string; q?: string; id?: string; name?: string; image?: string };
type Collector = {
  id: string; name: string; city: string; blurb: string; capacity: number; capacity_note: string;
  lifetime_spend: number; orders: number; timeline: TimelineEvent[]; event_count: number;
  purchases: { count: number; low: number | null; typical: number | null; high: number | null };
};
type Book = { lots: Piece[]; holdings: Piece[]; collectors: Collector[]; live: boolean };
type Pick_ = { lot: string; ask: number; resale: number; buyer: string | null; rank: number | null; fit: number; value: number };
type Demand = { collector: string; rank: number; rank_full: number; rank_orders: number; rank_tags: number; fit: number; affordable: boolean; over_by: number; stretch: number; vs_largest: number | null; passed: boolean };
type Result = {
  portfolio: { picks: Pick_[]; spent: number; budget: number; unspent: number; gross_margin: number; value: number; stretch_cost: number; unplaced_capital: number };
  stress: { collector: string; value: number; value_lost: number; unplaced_capital: number; unplaced: string[] }[];
  compare: { key: string; name: string; note: string; lots: string[]; spent: number; gross_margin: number; value: number; unplaced_capital: number; pieces: number; worst_loss: number }[];
  frontier: { budget: number; value: number; spent: number; pieces: number }[];
  demand: Record<string, Demand[]>;
  holdings: { id: string; best: { collector: string; rank: number }[]; reach: number; status: string }[];
  drift: Record<string, { gap: number; rising: string[]; fading: string[] }>;
  meta: { source: string; rank_ms: number; solve_ms: number; calls: number };
};
type Signal = { type: "search" | "view"; q?: string; id?: string };
type Settings = { fit_decay: number; holding_penalty: number; max_rank: number; slots: number; recency: number; capacity_tolerance: number; stretch_cost: number; relative: number };
type WhatIf = { feasible: boolean; reason?: string; already_in?: boolean; value_delta?: number; margin_delta?: number; displaced?: string[]; added?: string[]; buyer?: string | null; rank?: number | null };

const usd = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
const usdK = (n: number) => (Math.abs(n) >= 1000 ? `$${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k` : `$${Math.round(n)}`);
const signed = (n: number) => `${n >= 0 ? "+" : "−"}${usd(Math.abs(n))}`;
const MODES = [
  { key: "value", label: "Max value", res: 0 },
  { key: "balanced", label: "Balanced", res: 0.5 },
  { key: "hardened", label: "Buyer-proof", res: 0.9 },
];
const DEFAULTS: Settings = { fit_decay: 4, holding_penalty: 0.15, max_rank: 8, slots: 2, recency: 0.6, capacity_tolerance: 0.25, stretch_cost: 0.5, relative: 1 };
const fill = (v: number, min: number, max: number) => ({ "--p": `${((v - min) / (max - min)) * 100}%` }) as CSSProperties;
type Toast = { head: string; ms: number; added: string[]; removed: string[] };
type Bought = { lot: string; buyer: string | null; ask: number; resale: number };
const OPENING_LOTS = 20; // the rest of the batch stays back as simulated new offers
const OFFERS_PER_REVEAL = 2;

export default function App() {
  const [book, setBook] = useState<Book | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [budget, setBudget] = useState(80000);
  const [mode, setMode] = useState("value");
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [showSettings, setShowSettings] = useState(false);
  const [signals, setSignals] = useState<Record<string, Signal[]>>({});
  const [passes, setPasses] = useState<[string, string][]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [lotOpen, setLotOpen] = useState<string | null>(null);
  const [collectorOpen, setCollectorOpen] = useState<string | null>(null);
  const [credits, setCredits] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const [offDesk, setOffDesk] = useState<Set<string>>(new Set());
  const [revealed, setRevealed] = useState(0);
  const [bought, setBought] = useState<Bought[]>([]);
  const prevPicks = useRef<Set<string> | null>(null);
  const pendingToast = useRef<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    fetch("/api/book").then((r) => r.json()).then(setBook).catch(() => setErr("Could not load the book."));
  }, []);

  const opening = useMemo(() => (book?.lots ?? []).slice(0, OPENING_LOTS), [book]);
  const offers = useMemo(() => (book?.lots ?? []).slice(OPENING_LOTS), [book]);
  const newOffers = useMemo(() => offers.slice(0, revealed), [offers, revealed]);
  const radarLots = useMemo(() => [...newOffers, ...opening], [newOffers, opening]);
  const committedAsk = bought.reduce((a, x) => a + x.ask, 0);
  const available = Math.max(0, budget - committedAsk);

  const body = useMemo(() => {
    const isBought = new Set(bought.map((x) => x.lot));
    return {
      budget: available, ...settings, resilience: MODES.find((m) => m.key === mode)!.res, signals, passes,
      radar: radarLots.map((l) => l.id),
      desk: radarLots.map((l) => l.id).filter((id) => !offDesk.has(id) && !isBought.has(id)),
      committed: bought.map((x) => ({ lot: x.lot, buyer: x.buyer })),
    };
  }, [available, settings, mode, signals, passes, radarLots, offDesk, bought]);

  useEffect(() => {
    if (!book) return;
    const id = ++seq.current;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const r = await fetch("/api/portfolio", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "The solver did not answer.");
        const data: Result = await r.json();
        if (id !== seq.current) return;
        setRes(data);
        setErr(null);
      } catch (e) {
        if (id === seq.current) setErr((e as Error).message);
      } finally {
        if (id === seq.current) setBusy(false);
      }
    }, 90);
    return () => clearTimeout(t);
  }, [body, book]);

  const lotBy = useMemo(() => Object.fromEntries((book?.lots ?? []).concat(book?.holdings ?? []).map((l) => [l.id, l])), [book]);
  const colBy = useMemo(() => Object.fromEntries((book?.collectors ?? []).map((c) => [c.id, c])), [book]);
  const picks = useMemo(() => Object.fromEntries((res?.portfolio.picks ?? []).map((p) => [p.lot, p])), [res]);

  useEffect(() => {
    if (!res) return;
    const now = new Set(res.portfolio.picks.map((p) => p.lot));
    const prev = prevPicks.current;
    prevPicks.current = now;
    if (!prev) return;
    const added = [...now].filter((x) => !prev.has(x));
    const justBought = new Set(bought.map((x) => x.lot));
    const removed = [...prev].filter((x) => !now.has(x) && !justBought.has(x));
    setFlash(new Set(added));
    if (pendingToast.current) {
      setToast({ head: pendingToast.current, ms: res.meta.rank_ms, added: added.map((x) => lotBy[x]?.name), removed: removed.map((x) => lotBy[x]?.name) });
      pendingToast.current = null;
      setTimeout(() => setToast(null), 8000);
    }
    const t = setTimeout(() => setFlash(new Set()), 1600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [res, lotBy]);

  const buy = useCallback((x: Pick_) => {
    pendingToast.current = `Bought ${lotBy[x.lot]?.name} for ${usd(x.ask)}. ${usd(Math.max(0, available - x.ask))} still available.`;
    setBought((cur) => [...cur, { lot: x.lot, buyer: x.buyer, ask: x.ask, resale: x.resale }]);
    setLotOpen(null);
  }, [lotBy, available]);

  const undoBuy = useCallback((lot: string) => {
    pendingToast.current = `Undid the purchase of ${lotBy[lot]?.name}.`;
    setBought((cur) => cur.filter((x) => x.lot !== lot));
  }, [lotBy]);

  const toggleDesk = useCallback((id: string) => {
    const leaving = !offDesk.has(id);
    pendingToast.current = `${lotBy[id]?.name} ${leaving ? "taken off" : "sent to"} the desk.`;
    setOffDesk((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, [offDesk, lotBy]);

  const revealOffers = useCallback(() => {
    const next = offers.slice(revealed, revealed + OFFERS_PER_REVEAL);
    if (!next.length) return;
    pendingToast.current = `${next.length} new ${next.length > 1 ? "offers" : "offer"} on the radar: ${next.map((l) => l.name).join(", ")}. Not on the desk until you send them.`;
    setOffDesk((cur) => new Set([...cur, ...next.map((l) => l.id)]));
    setRevealed((n) => n + next.length);
  }, [offers, revealed]);

  const addSignal = useCallback((cid: string, s: Signal, label: string) => {
    pendingToast.current = `${colBy[cid]?.name}: ${label}.`;
    setSignals((cur) => ({ ...cur, [cid]: [...(cur[cid] ?? []), s] }));
  }, [colBy]);

  const togglePass = useCallback((lot: string, cid: string) => {
    setPasses((cur) => (cur.some(([l, c]) => l === lot && c === cid) ? cur.filter(([l, c]) => !(l === lot && c === cid)) : [...cur, [lot, cid]]));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setLotOpen(null); setCollectorOpen(null); setCredits(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!book) return <div className="pad muted">{err ?? "Opening the book…"}</div>;

  const p = res?.portfolio;
  const book_ = res?.compare.find((c) => c.key === "book");
  const trophyAsk = Math.max(...radarLots.map((l) => l.ask));
  const boughtIds = new Set(bought.map((x) => x.lot));
  const poolSize = radarLots.length - bought.length;
  const editCount = Object.values(signals).reduce((a, b) => a + b.length, 0) + passes.length + bought.length + revealed
    + [...offDesk].filter((id) => !newOffers.some((l) => l.id === id)).length;
  const placedTo = (cid: string) => (p?.picks ?? []).filter((x) => x.buyer === cid);
  const stretchOf = (lot: string, cid: string) => res?.demand[lot]?.find((r) => r.collector === cid)?.stretch ?? 0;
  const timesLargest = (lot: string, cid: string) => res?.demand[lot]?.find((r) => r.collector === cid)?.vs_largest ?? 0;

  return (
    <div className="app">
      <div className="bar">
        <span className="brand">
          <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M7 2.5h10L21.5 7v10L17 21.5H7L2.5 17V7z" fill="var(--emerald-deep)" stroke="var(--emerald)" strokeWidth="1.3" />
            <path d="M9 7h6l2 2v6l-2 2H9l-2-2V9z" fill="none" stroke="var(--emerald)" strokeWidth="1.1" />
          </svg>
          <span className="logo">The Book</span>
        </span>
        <span className="tag">Know your buyers. Own the right stones.</span>
        <span className="spacer" />
        <span className="status">
          <span className={`dot ${res?.meta.source === "snapshot" ? "off" : ""} ${busy ? "busy" : ""}`} />
          {res ? `BehaviorGPT ${res.meta.source}: ${res.meta.calls} rankings in ${res.meta.rank_ms} ms, solved in ${res.meta.solve_ms} ms` : "Reading the book…"}
        </span>
        <span className="invented">Invented data, not market prices</span>
      </div>

      <div className="band">
        <div className="band-budget">
          <label className="lbl" htmlFor="budget">Capital to work with</label>
          <div className="budget">{usd(budget)}</div>
          <div className="budget-sub">{bought.length ? `${usd(committedAsk)} committed, ${usd(available)} available` : "Available, not a target to spend"}</div>
          <input id="budget" className="range" type="range" min={10000} max={200000} step={1000} value={budget} style={fill(budget, 10000, 200000)}
            onChange={(e) => setBudget(+e.target.value)} />
        </div>
        <div className="band-alloc">
          <div className="alloc-head">
            <div className="alloc-line" aria-live="polite">
              {!p ? "Reading the book…"
                : focus ? (() => {
                  const mine = placedTo(focus);
                  return mine.length
                    ? <><b>{colBy[focus]?.name}</b> would take {mine.length} {mine.length > 1 ? "pieces" : "piece"}, <b>{usd(mine.reduce((a, x) => a + x.ask, 0))}</b> of the proposed buys.</>
                    : <>None of the proposed buys would go to <b>{colBy[focus]?.name}</b>.</>;
                })()
                : p.picks.length === 0 ? "Nothing clears the bar at this budget."
                : <><b>{bought.length ? "Proposed next:" : "Proposed buys, nothing bought yet:"}</b> {usd(p.spent)} on {p.picks.length} of {poolSize} lots, {usd(p.unspent)} stays available.</>}
            </div>
            <span className="alloc-key">Bar: share of budget</span>
          </div>
          <Allocation picks={p?.picks ?? []} budget={available || 1} spent={p?.spent ?? 0} lotBy={lotBy} colBy={colBy} focus={focus} flash={flash}
            open={(id) => { setCollectorOpen(null); setCredits(false); setLotOpen(id); }} />
        </div>
        <div className="band-ledger">
          <Line label="Paper margin" sub="Your resale estimates minus ask" value={p ? usd(p.gross_margin) : "…"} />
          <Line label="Fit-weighted value" sub="Margin × rank fit, less holding" value={p ? usd(p.value) : "…"} />
          <Line label="If one buyer walks" sub={res?.stress[0] ? `Worst case: ${colBy[res.stress[0].collector]?.name}` : ""} value={book_ ? `−${usd(book_.worst_loss)}` : "…"} tone="am" />
        </div>
      </div>

      {err && <div className="pad red">{err}</div>}

      <div className="main">
        <div className="col">
          <div className="head"><h2>Collector book</h2><span className="aside">{book.collectors.length} collectors</span></div>
          <div className="scroll collectors-scroll">
            {book.collectors.map((c) => {
              const placed = placedTo(c.id);
              const live = signals[c.id]?.length ?? 0;
              return (
                <button key={c.id} className={`collector ${focus === c.id ? "on" : ""}`}
                  onMouseEnter={() => setFocus(c.id)} onMouseLeave={() => setFocus(null)} onFocus={() => setFocus(c.id)} onBlur={() => setFocus(null)}
                  onClick={() => setCollectorOpen(c.id)}>
                  <div className="c-name">{c.name}</div>
                  <div className="c-cap">{usdK(c.capacity)}</div>
                  <div className="c-city">{live > 0 ? <span className="am">{live} {live > 1 ? "signals" : "signal"} today</span> : c.city}</div>
                  <div className="c-placed" aria-label={placed.length ? `${placed.length} placed` : undefined}>
                    {placed.map((x) => <img key={x.lot} src={lotBy[x.lot]?.image} alt="" title={lotBy[x.lot]?.name} />)}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="pad note">Hover a collector to light the lots by their ranking. Click to log a signal.</div>
        </div>

        <div className="col col-radar">
          <div className="head">
            <h2>Deal Radar</h2>
            <span className="aside">{poolSize} incoming {poolSize === 1 ? "lot" : "lots"}{offDesk.size > 0 ? `, ${radarLots.filter((l) => !offDesk.has(l.id) && !boughtIds.has(l.id)).length} on the desk` : ""}</span>
            {revealed < offers.length && <button className="link" title="Reveals offers already in the catalog, so their rankings are real but their arrival is staged" onClick={revealOffers}>Simulate new offers ({offers.length - revealed} left)</button>}
            <span className="aside push">
              {focus ? `Lit by ${colBy[focus]?.name}'s ranking, brightest first` : "Lit lots are in the proposed buys"}
            </span>
          </div>
          <div className="scroll">
            <div className="lots">
              {radarLots.map((l) => {
                const pick = picks[l.id];
                const isNew = newOffers.some((x) => x.id === l.id);
                const isBought = boughtIds.has(l.id);
                const onDesk = !offDesk.has(l.id) && !isBought;
                const owner = bought.find((x) => x.lot === l.id)?.buyer;
                const best = res?.demand[l.id]?.find((x) => x.rank <= settings.max_rank && x.affordable && !x.passed);
                const d = focus ? res?.demand[l.id]?.find((x) => x.collector === focus) : null;
                const lit = d ? ({ "--b": 0.14 + 0.86 * d.fit, "--s": 0.35 + 0.65 * d.fit }) as CSSProperties : undefined;
                return (
                  <div key={l.id} className="lot-cell">
                  <button className={`lot ${pick ? "in" : ""} ${isBought ? "bought" : ""} ${flash.has(l.id) ? "flash" : ""}`} style={lit} title={l.name} onClick={() => setLotOpen(l.id)}>
                    <div className="thumb">
                      <img src={l.image} alt="" loading="lazy" />
                      {isBought ? <span className="plate top">Bought</span>
                        : d ? <span className={`plate rank ${d.rank <= 3 ? "top" : d.rank <= settings.max_rank ? "near" : ""}`}>#{d.rank}</span>
                        : isNew ? <span className="plate trophy">New offer</span>
                        : l.ask === trophyAsk ? <span className="plate trophy">Trophy</span> : null}
                    </div>
                    <div className="ticket">
                      <div className="t-name"><span className="t-no">{l.lot_no}</span>{l.name}</div>
                      <div className="t-px"><span>{usd(l.ask)}</span><span className="est">est. {usd(l.resale)}</span></div>
                      <div className="t-to">
                        {isBought ? (owner ? <>Bought for <b>{colBy[owner]?.name}</b></> : "Bought")
                          : pick ? (pick.buyer ? <>For <b>{colBy[pick.buyer]?.name}</b>, #{pick.rank}</> : <span className="am">No buyer placed</span>)
                          : best ? <>{onDesk ? "Pass. " : ""}Best match {colBy[best.collector]?.name}, #{best.rank}</>
                          : "No collector in range"}
                      </div>
                    </div>
                  </button>
                  {!isBought && <button className={`send ${onDesk ? "on" : ""}`} aria-pressed={onDesk} onClick={() => toggleDesk(l.id)}>{onDesk ? "On desk" : "Send to desk"}</button>}
                  </div>
                );
              })}
            </div>
            {res && (
              <div className="lower">
                <div>
                  <div className="head flat"><h3>What the next dollar buys</h3></div>
                  <Frontier data={res.frontier} budget={available} />
                </div>
                <div>
                  <div className="head flat"><h3>Same budget, other ways to choose</h3></div>
                  <table>
                    <thead><tr><th>Strategy</th><th>Pieces</th><th>Paper margin</th><th>Fit value</th><th>Unplaced</th><th>One buyer walks</th></tr></thead>
                    <tbody>
                      {res.compare.map((c) => (
                        <tr key={c.key} className={c.key === "book" ? "hl" : ""} title={c.note}>
                          <td className="text">{c.name}<div className="sub">{c.note}</div></td>
                          <td>{c.pieces}</td><td>{usdK(c.gross_margin)}</td><td>{usdK(c.value)}</td>
                          <td>{c.unplaced_capital ? usdK(c.unplaced_capital) : "–"}</td><td>{c.worst_loss ? `−${usdK(c.worst_loss)}` : "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="pad note">All four are scored by the same rules and BehaviorGPT fit, so this compares choices under this tool's assumptions. It is not a forecast of sales.</div>
                </div>
              </div>
            )}
            {res && (
              <div className="section-top table-scroll">
                <div className="head flat"><h3>Your current inventory, read against the same collectors</h3></div>
                <table>
                  <thead><tr><th>Piece</th><th>Cost basis</th><th>Collectors in range</th><th>Closest collector</th><th>Status</th></tr></thead>
                  <tbody>
                    {res.holdings.map((h) => (
                      <tr key={h.id}>
                        <td className="text">{lotBy[h.id]?.name}</td>
                        <td>{usd(lotBy[h.id]?.ask ?? 0)}</td>
                        <td>{h.reach}</td>
                        <td className="text" style={{ textAlign: "right" }}>{colBy[h.best[0]?.collector]?.name}, #{h.best[0]?.rank}</td>
                        <td className={h.status === "live" ? "em" : h.status === "thin" ? "am" : "red"}>{h.status === "stale" ? "Stale: move it" : h.status === "thin" ? "Thin: one collector" : "In demand"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <div className="col col-desk">
          <div className="head">
            <h2>Capital Desk</h2>
            <span className="aside">Proposed buys</span>
            <button className="link push" onClick={() => setShowSettings((s) => !s)}>{showSettings ? "Hide assumptions" : "Assumptions"}</button>
          </div>
          <div className="desk-tools">
            <div className="segctl" role="group" aria-label="Objective">
              {MODES.map((m) => <button key={m.key} className={mode === m.key ? "on" : ""} aria-pressed={mode === m.key} onClick={() => setMode(m.key)}>{m.label}</button>)}
            </div>
            {editCount > 0 && <button className="link" onClick={() => { setSignals({}); setPasses([]); setBought([]); setOffDesk(new Set()); setRevealed(0); }}>Reset {editCount} {editCount > 1 ? "edits" : "edit"}</button>}
          </div>
          {showSettings && <Assumptions s={settings} set={setSettings} />}
          <div className="scroll">
            {bought.length > 0 && (
              <>
                <div className="head flat"><h3>Committed</h3><span className="aside push">{usd(committedAsk)} spent</span></div>
                {bought.map((x) => (
                  <div key={x.lot} className="bought-row">
                    <img src={lotBy[x.lot]?.image} alt="" />
                    <div style={{ minWidth: 0 }}>
                      <div className="n" title={lotBy[x.lot]?.name}>{lotBy[x.lot]?.name}</div>
                      <div className="b">{x.buyer ? <>For <span className="who">{colBy[x.buyer]?.name}</span></> : "No buyer placed"}, {usd(x.ask)}</div>
                    </div>
                    <button className="link" onClick={() => undoBuy(x.lot)}>Undo</button>
                  </div>
                ))}
                <div className="head flat"><h3>Proposed next</h3><span className="aside push">{usd(available)} available</span></div>
              </>
            )}
            {p?.picks.length === 0 && <div className="pad muted">{available === 0 ? "No capital left to propose anything." : "Nothing here clears the bar. That's a fine answer: the capital stays available."}</div>}
            {p?.picks.map((x) => (
              <div key={x.lot} className="pick-row">
              <button className="pick" onClick={() => setLotOpen(x.lot)}>
                <img src={lotBy[x.lot]?.image} alt="" />
                <div style={{ minWidth: 0 }}>
                  <div className="n" title={lotBy[x.lot]?.name}>{lotBy[x.lot]?.name}</div>
                  <div className="b">{x.buyer ? <>Call <span className="who">{colBy[x.buyer]?.name}</span>, ranks it #{x.rank} of {poolSize}{stretchOf(x.lot, x.buyer) > 0 && <span className="am">, {usd(stretchOf(x.lot, x.buyer))} over capacity</span>}{timesLargest(x.lot, x.buyer) > 1 && <span>, {timesLargest(x.lot, x.buyer).toFixed(1)}× their largest purchase</span>}</> : <span className="am">No buyer placed</span>}</div>
                </div>
                <div className="r">{usd(x.ask)}<div>est. {usd(x.resale)}</div></div>
              </button>
              <button className="buy" title={`Commit to buying this for ${usd(x.ask)}`} onClick={() => buy(x)}>Buy</button>
              </div>
            ))}
            {p && p.picks.length > 0 && (
              <div className="total">
                <span>Total, {p.picks.length} {p.picks.length > 1 ? "pieces" : "piece"}</span>
                <span className="r">{usd(p.spent)}<div>est. {usd(p.spent + p.gross_margin)}</div></span>
              </div>
            )}
            {res && res.stress.length > 0 && (
              <>
                <div className="head flat"><h3>If this buyer walks</h3><span className="aside push">The buys are re-placed</span></div>
                <table>
                  <thead><tr><th>Buyer lost</th><th>Value lost</th><th>Left unplaced</th></tr></thead>
                  <tbody>
                    {res.stress.slice(0, 6).map((s) => (
                      <tr key={s.collector} onMouseEnter={() => setFocus(s.collector)} onMouseLeave={() => setFocus(null)}><td className="text">{colBy[s.collector]?.name}</td><td>{s.value_lost >= 1 ? `−${usd(s.value_lost)}` : "$0"}</td><td>{s.unplaced_capital ? <span className="am">{usd(s.unplaced_capital)}</span> : "none"}</td></tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      </div>

      <footer>
        <span>Built at <a href="https://www.sundai.club/" target="_blank" rel="noreferrer">Sundai</a></span>
        <span>Collectors, events, asks and resale estimates are invented for this demo. Rankings are real BehaviorGPT output on them.</span>
        <span>Fit comes from rank order. It is not a probability of sale.</span>
        <span className="spacer" />
        <button className="link" onClick={() => setCredits(true)}>Photo credits</button>
      </footer>

      {lotOpen && lotBy[lotOpen] && res && (
        <LotDrawer lot={lotBy[lotOpen]} res={res} colBy={colBy} body={body} total={poolSize} passes={passes} togglePass={togglePass} lotBy={lotBy}
          maxRank={settings.max_rank} onClose={() => setLotOpen(null)} logView={(cid) => addSignal(cid, { type: "view", id: lotOpen }, `looked at ${lotBy[lotOpen].name}`)} />
      )}
      {collectorOpen && colBy[collectorOpen] && res && (
        <CollectorDrawer c={colBy[collectorOpen]} res={res} lotBy={lotBy} signals={signals[collectorOpen] ?? []} tolerance={settings.capacity_tolerance}
          onClose={() => setCollectorOpen(null)}
          addSearch={(q) => addSignal(collectorOpen, { type: "search", q }, `asked about “${q}”`)} />
      )}
      {credits && <Credits lots={Object.values(lotBy)} onClose={() => setCredits(false)} />}
      {toast && (
        <div className="toast" role="status">
          <div>{toast.head} Re-ranked in {toast.ms} ms.</div>
          {toast.added.map((n) => <div className="tl" key={n}><span className="in">In</span><span>{n}</span></div>)}
          {toast.removed.map((n) => <div className="tl" key={n}><span className="out">Out</span><span className="ink2">{n}</span></div>)}
          {toast.added.length + toast.removed.length === 0 && <div className="note">The proposed buys hold.</div>}
        </div>
      )}
    </div>
  );
}

function Line({ label, sub, value, tone }: { label: string; sub?: string; value: string; tone?: string }) {
  return (
    <div className="line">
      <div className="line-l"><div>{label}</div><div>{sub}</div></div>
      <div className={`line-v ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

function Allocation({ picks, budget, spent, lotBy, colBy, focus, flash, open }: {
  picks: Pick_[]; budget: number; spent: number; lotBy: Record<string, Piece>; colBy: Record<string, Collector>; focus: string | null; flash: Set<string>; open: (id: string) => void;
}) {
  const ordered = [...picks].sort((a, b) => (lotBy[a.lot]?.lot_no ?? 0) - (lotBy[b.lot]?.lot_no ?? 0));
  const dry = budget - spent;
  const row = useRef<HTMLDivElement>(null);
  const [hot, setHot] = useState<string | null>(null);
  // a piece that just came in may sit past the edge of the row, so bring it into view
  useEffect(() => {
    const box = row.current;
    const fresh = box?.querySelector<HTMLElement>(".tile.flash");
    if (!box || !fresh) return;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    box.scrollTo({ left: fresh.offsetLeft - 8, behavior: calm ? "auto" : "smooth" });
  }, [flash]);
  const dimmed = (x: Pick_) => (focus && x.buyer !== focus ? "dim" : "");
  return (
    <>
      <div className="share" role="img" aria-label={`${usd(spent)} of ${usd(budget)} proposed across ${picks.length} lots, ${usd(dry)} left unspent`}>
        {ordered.map((x) => (
          <i key={x.lot} className={`${dimmed(x)} ${hot === x.lot ? "hot" : ""}`} style={{ flexBasis: `${(x.ask / budget) * 100}%` }}
            title={`${lotBy[x.lot]?.name}: ${usd(x.ask)}, ${Math.round((x.ask / budget) * 100)}% of the budget`} />
        ))}
      </div>
      <div className="tiles" ref={row} role="group" aria-label="Proposed buys"
        onWheel={(e) => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) e.currentTarget.scrollLeft += e.deltaY; }}>
        {ordered.map((x) => {
          const said = `${lotBy[x.lot]?.name}, ${usd(x.ask)}, ${x.buyer ? `for ${colBy[x.buyer]?.name}` : "no buyer placed"}`;
          return (
            <button key={x.lot} className={["tile", dimmed(x), x.buyer ? "" : "unplaced", flash.has(x.lot) ? "flash" : ""].join(" ")} title={said} aria-label={said}
              onClick={() => open(x.lot)} onMouseEnter={() => setHot(x.lot)} onMouseLeave={() => setHot(null)} onFocus={() => setHot(x.lot)} onBlur={() => setHot(null)}>
              <span className="tile-img"><img src={lotBy[x.lot]?.image} alt="" /></span>
              <span className="tile-px">{usd(x.ask)}</span>
            </button>
          );
        })}
      </div>
    </>
  );
}

function Assumptions({ s, set }: { s: Settings; set: (x: Settings) => void }) {
  const Row = (k: keyof Settings, label: string, min: number, max: number, step: number, fmt: (n: number) => string) => (
    <label key={k}>{label}: <span className="ink2">{fmt(s[k])}</span>
      <input className="range" type="range" min={min} max={max} step={step} value={s[k]} style={fill(s[k], min, max)} onChange={(e) => set({ ...s, [k]: +e.target.value })} />
    </label>
  );
  return (
    <div className="settings">
      {Row("recency", "Recent behavior vs purchases", 0, 1, 0.05, (n) => `${Math.round(n * 100)}/${Math.round((1 - n) * 100)}`)}
      {Row("relative", "Favor what sets a collector apart", 0, 2, 0.25, (n) => `${n}`)}
      {Row("fit_decay", "Fit falls off by rank", 1, 12, 0.5, (n) => `${n}`)}
      {Row("max_rank", "Candidate buyer down to rank", 1, 24, 1, (n) => `#${n}`)}
      {Row("slots", "Pieces per collector", 1, 5, 1, (n) => `${n}`)}
      {Row("stretch_cost", "Value lost per $1 over capacity", 0, 2, 0.1, (n) => `$${n.toFixed(2)}`)}
      {Row("capacity_tolerance", "Furthest over capacity", 0, 1, 0.05, (n) => `${Math.round(n * 100)}%`)}
      {Row("holding_penalty", "Holding penalty on ask", 0, 0.5, 0.01, (n) => `${Math.round(n * 100)}%`)}
    </div>
  );
}

function Frontier({ data, budget }: { data: Result["frontier"]; budget: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(480);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const o = new ResizeObserver((e) => setW(e[0].contentRect.width));
    o.observe(ref.current);
    return () => o.disconnect();
  }, []);
  const h = 170, L = 52, R = 14, T = 12, B = 24;
  const maxB = data[data.length - 1]?.budget ?? 200000;
  const maxV = Math.max(1, ...data.map((d) => d.value));
  const x = (b: number) => L + (b / maxB) * (w - L - R);
  const y = (v: number) => T + (1 - v / maxV) * (h - T - B);
  const line = data.map((d, i) => `${i ? "L" : "M"}${x(d.budget).toFixed(1)},${y(d.value).toFixed(1)}`).join(" ");
  const nearest = data.reduce((a, d) => (Math.abs(d.budget - budget) < Math.abs(a.budget - budget) ? d : a), data[0]);
  const hv = hover === null ? null : data[hover];
  const prev = hover ? data[hover - 1] : null;
  const yTicks = [0, maxV / 2, maxV];
  return (
    <div ref={ref} style={{ position: "relative" }}>
      {table ? (
        <div style={{ maxHeight: 170, overflow: "auto" }}>
          <table><thead><tr><th>Budget</th><th>Fit value</th><th>Deployed</th><th>Pieces</th></tr></thead>
            <tbody>{data.map((d) => <tr key={d.budget}><td>{usd(d.budget)}</td><td>{usd(d.value)}</td><td>{usd(d.spent)}</td><td>{d.pieces}</td></tr>)}</tbody></table>
        </div>
      ) : (
        <svg width={w} height={h} role="img" aria-label="Fit-weighted value at each budget level"
          onMouseMove={(e) => {
            const box = e.currentTarget.getBoundingClientRect();
            const b = ((e.clientX - box.left - L) / (w - L - R)) * maxB;
            let best = 0;
            data.forEach((d, i) => { if (Math.abs(d.budget - b) < Math.abs(data[best].budget - b)) best = i; });
            setHover(best);
          }} onMouseLeave={() => setHover(null)}>
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={L} x2={w - R} y1={y(t)} y2={y(t)} stroke="var(--rule)" />
              <text x={L - 6} y={y(t) + 4} textAnchor="end" fill="var(--muted)" fontSize={11}>{usdK(Math.round(t))}</text>
            </g>
          ))}
          {[50000, 100000, 150000, 200000].map((t) => (
            <text key={t} x={Math.min(x(t), w - R - 16)} y={h - 7} textAnchor="middle" fill="var(--muted)" fontSize={11}>{usdK(t)}</text>
          ))}
          <path d={line} fill="none" stroke="var(--emerald-line)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          <line x1={x(budget)} x2={x(budget)} y1={T} y2={h - B} stroke="var(--amber)" strokeWidth={1} strokeDasharray="3 3" />
          {nearest && <circle cx={x(nearest.budget)} cy={y(nearest.value)} r={4.5} fill="var(--amber)" stroke="var(--surface)" strokeWidth={2} />}
          {hv && (
            <>
              <line x1={x(hv.budget)} x2={x(hv.budget)} y1={T} y2={h - B} stroke="var(--rule-char)" />
              <circle cx={x(hv.budget)} cy={y(hv.value)} r={4} fill="var(--emerald-line)" stroke="var(--surface)" strokeWidth={2} />
            </>
          )}
        </svg>
      )}
      {!table && hv && (
        <div className="tooltip" style={{ left: Math.min(x(hv.budget) + 10, w - 190), top: 10 }}>
          Budget {usd(hv.budget)}<br />Fit value {usd(hv.value)}<br />{hv.pieces} pieces, {usd(hv.spent)} deployed
          {prev && <><br />Last $10k added {signed(hv.value - prev.value)}</>}
        </div>
      )}
      <div className="pad note row" style={{ justifyContent: "space-between", paddingTop: 2 }}>
        <span>Fit-weighted value at each budget. Where the line flattens, more capital stops buying collector demand.</span>
        <button className="link" onClick={() => setTable((t) => !t)}>{table ? "Chart" : "Table"}</button>
      </div>
    </div>
  );
}

function LotDrawer({ lot, res, colBy, lotBy, body, total, passes, togglePass, maxRank, onClose, logView }: {
  lot: Piece; res: Result; colBy: Record<string, Collector>; lotBy: Record<string, Piece>; body: object; total: number; passes: [string, string][];
  togglePass: (l: string, c: string) => void; maxRank: number; onClose: () => void; logView: (cid: string) => void;
}) {
  const pick = res.portfolio.picks.find((x) => x.lot === lot.id);
  const rows = res.demand[lot.id] ?? [];
  const [what, setWhat] = useState<WhatIf | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => setWhat(null), [lot.id, body]);
  const force = async () => {
    setLoading(true);
    const r = await fetch("/api/whatif", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...body, lot: lot.id }) });
    setWhat(await r.json());
    setLoading(false);
  };
  const eligible = rows.filter((r) => r.rank <= maxRank && r.affordable && !r.passed);
  const placed = new Set(res.portfolio.picks.map((x) => x.buyer));
  const nearest = rows.filter((r) => r.rank <= maxRank && !r.affordable && !r.passed).sort((a, b) => a.over_by - b.over_by)[0];
  const reason = pick
    ? pick.buyer ? `Placed with ${colBy[pick.buyer]?.name}, who ranks it #${pick.rank} of ${total}.` : "Bought, but no buyer could be placed."
    : eligible.length === 0
      ? nearest
        ? `No collector who ranks this within #${maxRank} has the capacity for ${usd(lot.resale)}. Closest: ${colBy[nearest.collector]?.name}, over by ${usd(nearest.over_by)}.`
        : `No collector ranks this within #${maxRank}.`
      : eligible.every((r) => placed.has(r.collector))
        ? `Everyone in range for it (${eligible.slice(0, 3).map((r) => colBy[r.collector]?.name).join(", ")}) already has a piece placed.`
        : "Collectors are in range, but this budget earns more fit-weighted value elsewhere. Force it in to see the cost.";
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" aria-label={lot.name}>
        <div className="dhead"><span className="lbl">{lot.lot_no ? `Lot ${lot.lot_no}` : "In your inventory"}</span><button className="btn" onClick={onClose}>Close</button></div>
        <img className="hero" src={lot.image} alt={lot.name} />
        <div className="dsec">
          <h2 className="title">{lot.name}</h2>
          <div className="note" style={{ marginTop: 4 }}>{lot.description}</div>
          <div className="kv">
            <div><div className="lbl">Ask</div><div className="fig">{usd(lot.ask)}</div></div>
            <div><div className="lbl">Your resale est.</div><div className="fig">{usd(lot.resale)}</div></div>
            <div><div className="lbl">Paper margin</div><div className="fig">{Math.round(((lot.resale - lot.ask) / lot.ask) * 100)}%</div></div>
          </div>
        </div>
        <div className="dsec">
          <h3>Decision</h3>
          <div>{reason}</div>
          {!pick && (
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn primary" disabled={loading} onClick={force}>{loading ? "Solving…" : "See the cost of forcing it in"}</button>
            </div>
          )}
          {what && (what.feasible ? (
            <div style={{ marginTop: 8 }}>
              <div>Insisting on this lot changes fit-weighted value by <b className={(what.value_delta ?? 0) < 0 ? "red" : "em"}>{signed(what.value_delta ?? 0)}</b> and paper margin by <span className="num">{signed(what.margin_delta ?? 0)}</span>.</div>
              {!!what.displaced?.length && <div className="note">Pushes out: {what.displaced.map((x) => lotBy[x]?.name).join(", ")}.</div>}
              {!!what.added?.length && <div className="note">Brings in: {what.added.map((x) => lotBy[x]?.name).join(", ")}.</div>}
              <div className="note">{what.buyer ? `Would be placed with ${colBy[what.buyer]?.name} at #${what.rank}.` : "No collector could be placed against it."}</div>
            </div>
          ) : <div className="note" style={{ marginTop: 8 }}>{what.reason}</div>)}
        </div>
        <div className="dsec flush">
          <h3>Who ranks it where</h3>
          <table>
            <thead><tr><th>Collector</th><th title="Recent behavior and purchases blended, then adjusted for how much more this collector ranks the lot than the book does">Book</th><th title="Full behavior sequence">Seq</th><th title="Purchases only">Buys</th><th title="Tag-overlap baseline, not BehaviorGPT">Tags</th><th></th></tr></thead>
            <tbody>
              {rows.slice(0, 10).map((r) => {
                const passed = passes.some(([l, c]) => l === lot.id && c === r.collector);
                return (
                  <tr key={r.collector} className={`${pick?.buyer === r.collector ? "hl" : ""} ${passed ? "dim" : ""}`}>
                    <td className="text">{colBy[r.collector]?.name}{!r.affordable && <span className="muted">, {usd(r.over_by)} past the limit</span>}{r.stretch > 0 && <span className="am">, {usd(r.stretch)} over capacity</span>}{r.vs_largest !== null && <span className="muted">, {r.vs_largest.toFixed(1)}× largest purchase</span>}</td>
                    <td>#{r.rank}</td><td>#{r.rank_full}</td><td>#{r.rank_orders}</td>
                    <td className={Math.abs(r.rank_tags - r.rank_full) >= 8 ? "am" : ""}>#{r.rank_tags}</td>
                    <td><span className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="link" onClick={() => logView(r.collector)}>viewed</button>
                      <button className="link" onClick={() => togglePass(lot.id, r.collector)}>{passed ? "undo" : "passed"}</button>
                    </span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="pad note">Amber Tags: tag matching and BehaviorGPT disagree by 8+ places. That disagreement could be insight or noise, so treat it as a question to ask the collector. “Viewed” re-ranks that collector live. “Passed” only removes them as a buyer for this lot.</div>
        </div>
        <div className="dsec note">
          {lot.credit
            ? <>Stand-in photo: “{lot.credit.title}” by {lot.credit.author || "unknown"}, {lot.credit.license}, via <a href={lot.credit.landing_url} target="_blank" rel="noreferrer">{lot.credit.source}</a>. </>
            : "Placeholder art, not a photo of this piece. "}
          The lot itself, its ask and resale are invented.
        </div>
      </aside>
    </>
  );
}

function CollectorDrawer({ c, res, lotBy, signals, tolerance, onClose, addSearch }: {
  c: Collector; res: Result; lotBy: Record<string, Piece>; signals: Signal[]; tolerance: number; onClose: () => void; addSearch: (q: string) => void;
}) {
  const [q, setQ] = useState("");
  const [wider, setWider] = useState<{ id: string; name: string; image: string; form: string }[] | null>(null);
  useEffect(() => {
    setWider(null);
    fetch(`/api/collector/${c.id}/sourcing`).then((r) => r.json()).then((d) => setWider(d.pieces)).catch(() => setWider([]));
  }, [c.id]);
  const drift = res.drift[c.id];
  const label = (e: TimelineEvent) => (e.type === "search" ? "Asked" : e.type === "order" ? "Bought" : "Viewed");
  const submit = (text: string) => {
    const t = text.trim();
    if (t) { addSearch(t.slice(0, 120)); setQ(""); }
  };
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" aria-label={c.name}>
        <div className="dhead"><span className="lbl">Collector</span><button className="btn" onClick={onClose}>Close</button></div>
        <div className="dsec">
          <h2 className="title">{c.name}</h2>
          <div className="muted">{c.city}</div>
          <div className="note" style={{ marginTop: 4 }}>{c.blurb}</div>
          <div className="kv">
            <div><div className="lbl">Capacity</div><div className="fig">{usdK(c.capacity)}</div></div>
            <div><div className="lbl">Past spend</div><div className="fig">{usdK(c.lifetime_spend)}</div></div>
            <div><div className="lbl">Purchases</div><div className="fig">{c.orders}</div></div>
          </div>
          <div className="note" style={{ marginTop: 6 }}>{c.purchases.count > 0 && <>Past purchases ran {usd(c.purchases.low!)} to {usd(c.purchases.high!)}, typically {usd(c.purchases.typical!)}. </>}{c.capacity_note} Going over capacity lowers a lot's value, up to a limit of {usd(c.capacity * (1 + tolerance))}.</div>
        </div>
        <div className="dsec">
          <h3>Log a signal from today</h3>
          <form className="row" onSubmit={(e) => { e.preventDefault(); submit(q); }}>
            <input className="input" style={{ flex: 1, minWidth: 180 }} value={q} maxLength={120} placeholder="They called asking about…" onChange={(e) => setQ(e.target.value)} />
            <button className="btn primary" type="submit">Re-rank live</button>
          </form>
          <div className="row" style={{ marginTop: 6 }}>
            {["sapphire ring", "gold chain", "art deco", "loose emerald", "tennis bracelet"].map((s) => (
              <button key={s} className="sug" onClick={() => submit(s)}>{s}</button>
            ))}
          </div>
          {signals.length > 0 && <div className="note" style={{ marginTop: 6 }}>Logged today: {signals.map((s) => (s.q ? `“${s.q}”` : lotBy[s.id!]?.name)).join(", ")}</div>}
        </div>
        {drift && (
          <div className="dsec">
            <h3>Recent behavior vs what they buy</h3>
            <div className="note" style={{ marginBottom: 6 }}>Average gap of {drift.gap} places across this batch between the two rankings.</div>
            <div className="row" style={{ alignItems: "flex-start" }}>
              <div style={{ flex: 1, minWidth: 180 }}><div className="em" style={{ fontSize: 12.5, fontWeight: 500 }}>Rising with recent behavior</div>{drift.rising.map((x) => <div key={x} className="note">{lotBy[x]?.name}</div>)}</div>
              <div style={{ flex: 1, minWidth: 180 }}><div className="am" style={{ fontSize: 12.5, fontWeight: 500 }}>Fading</div>{drift.fading.map((x) => <div key={x} className="note">{lotBy[x]?.name}</div>)}</div>
            </div>
          </div>
        )}
        <div className="dsec">
          <h3>Last events BehaviorGPT read ({c.event_count} in all, invented)</h3>
          {c.timeline.map((e, i) => (
            <div className="event" key={i}>
              <span className={e.type === "order" ? "em" : "muted"}>{label(e)}</span>
              {e.image ? <img src={e.image} alt="" /> : <span />}
              <span>{e.name ?? `“${e.q}”`}</span>
            </div>
          ))}
        </div>
        <div className="dsec">
          <h3>Source for them: next in the wider catalog</h3>
          {wider === null && <div className="muted">Ranking…</div>}
          {wider?.length === 0 && <div className="muted">Needs a live BehaviorGPT connection.</div>}
          {wider?.map((w) => (
            <div className="event" key={w.id} style={{ gridTemplateColumns: "30px minmax(0,1fr)" }}>
              <img src={w.image} alt="" /><span>{w.name}</span>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

function Credits({ lots, onClose }: { lots: Piece[]; onClose: () => void }) {
  const credited = lots.filter((l) => l.credit);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" aria-label="Photo credits">
        <div className="dhead"><span className="lbl">Photo credits</span><button className="btn" onClick={onClose}>Close</button></div>
        <div className="dsec note">Photos stand in for fictional lots. Descriptions, asks and resale figures are invented and say nothing about the pictured objects or their owners. The full list for every image is in CREDITS.md in the repository.</div>
        <div className="dsec">
          {credited.length === 0 && <div className="note">Lot art is placeholder for now, so there are no photos to credit yet.</div>}
          {credited.map((l) => (
            <div key={l.id} className="note" style={{ marginBottom: 6 }}>
              <b className="ink2">{l.name}</b>: “{l.credit!.title}” by {l.credit!.author || "unknown"}, <a href={l.credit!.license_url} target="_blank" rel="noreferrer">{l.credit!.license}</a>, <a href={l.credit!.landing_url} target="_blank" rel="noreferrer">{l.credit!.source}</a>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}
