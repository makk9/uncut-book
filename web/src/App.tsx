import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent } from "react";

const LOT_DRAG = "application/x-the-book-lot";
const TILE_H = 76;

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
type Holding = { id: string; best: { collector: string; rank: number }[]; reach: number; viewed_by: string[]; status: "live" | "thin" | "stale" };
type Plan = { picks: Pick_[]; spent: number; budget: number; unspent: number; gross_margin: number; value: number; stretch_cost: number; unplaced_capital: number; ties?: Record<string, string[]> };
type Result = {
  portfolio: Plan;
  plan: Plan;
  next: Plan;
  compare: { key: string; name: string; note: string; lots: string[]; spent: number; gross_margin: number; value: number; unplaced_capital: number; pieces: number }[];
  frontier: { budget: number; value: number; spent: number; pieces: number }[];
  demand: Record<string, Demand[]>;
  holdings: Holding[];
  in_stock: Record<string, string[]>;
  drift: Record<string, { gap: number; rising: string[]; fading: string[] }>;
  meta: { source: string; rank_ms: number; solve_ms: number; calls: number };
};
type Signal = { type: "search" | "view"; q?: string; id?: string };
type Settings = { fit_decay: number; holding_penalty: number; max_rank: number; slots: number; recency: number; capacity_tolerance: number; stretch_cost: number; relative: number };

const usd = (n: number) => `${n < 0 ? "−" : ""}$${Math.abs(Math.round(n)).toLocaleString("en-US")}`;
const usdK = (n: number) => `${n < 0 ? "−" : ""}${Math.abs(n) >= 1000 ? `$${(Math.abs(n) / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k` : `$${Math.abs(Math.round(n))}`}`;
const signed = (n: number) => `${n >= 0 ? "+" : "−"}${usd(Math.abs(n))}`;
const DEFAULTS: Settings = { fit_decay: 4, holding_penalty: 0.15, max_rank: 8, slots: 2, recency: 0.6, capacity_tolerance: 0.25, stretch_cost: 0.5, relative: 1 };
const fill = (v: number, min: number, max: number) => ({ "--p": `${((v - min) / (max - min)) * 100}%` }) as CSSProperties;
type Toast = { head: string; ms: number | null; delta: string | null; moved: string[]; added: string[]; removed: string[] };
const OPENING_LOTS = 20; // the rest of the batch stays back as simulated new offers
const OFFERS_PER_REVEAL = 2;

export default function App() {
  const [book, setBook] = useState<Book | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [budget, setBudget] = useState(80000);
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
  const [revealed, setRevealed] = useState(0);
  const [plan, setPlan] = useState<string[]>([]);
  const [dragLot, setDragLot] = useState<string | null>(null);
  const [overParcel, setOverParcel] = useState(false);
  const prevSuggested = useRef<Set<string> | null>(null);
  const prevPlan = useRef<Plan | null>(null);
  const pendingToast = useRef<{ head: string; planEdit: boolean } | null>(null);
  const shownBuyers = useRef<Record<string, string>>({});
  const seq = useRef(0);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    fetch("/api/book").then((r) => r.json()).then(setBook).catch(() => setErr("Could not load the book."));
  }, []);

  const opening = useMemo(() => (book?.lots ?? []).slice(0, OPENING_LOTS), [book]);
  const offers = useMemo(() => (book?.lots ?? []).slice(OPENING_LOTS), [book]);
  const newOffers = useMemo(() => offers.slice(0, revealed), [offers, revealed]);
  const radarLots = useMemo(() => [...newOffers, ...opening], [newOffers, opening]);

  const body = useMemo(() => ({
    budget, ...settings, signals, passes, plan,
    radar: radarLots.map((l) => l.id),
  }), [budget, settings, signals, passes, plan, radarLots]);

  useEffect(() => {
    if (!book) return;
    const id = ++seq.current;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        // a tie goes to the buyer already on screen, so adding a lot doesn't change the name for no reason
        const prefer = Object.fromEntries(body.plan.flatMap((l) => (shownBuyers.current[l] ? [[l, shownBuyers.current[l]]] : [])));
        const r = await fetch("/api/portfolio", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...body, prefer }) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "The solver did not answer.");
        const data: Result = await r.json();
        if (id !== seq.current) return;
        shownBuyers.current = buyersOnScreen(data, body.max_rank);
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
  const planned = useMemo(() => Object.fromEntries((res?.plan.picks ?? []).map((p) => [p.lot, p])), [res]);
  const nextUp = useMemo(() => Object.fromEntries((res?.next.picks ?? []).map((p) => [p.lot, p])), [res]);

  useEffect(() => {
    if (!res) return;
    const now = new Set(res.portfolio.picks.map((p) => p.lot));
    const prev = prevSuggested.current;
    const before = prevPlan.current;
    prevSuggested.current = now;
    prevPlan.current = res.plan;
    if (!prev || !before) return;
    const added = [...now].filter((x) => !prev.has(x));
    const removed = [...prev].filter((x) => !now.has(x));
    const joined = res.plan.picks.map((x) => x.lot).filter((x) => !before.picks.some((y) => y.lot === x));
    setFlash(new Set([...added, ...joined]));
    if (pendingToast.current) {
      const { head, planEdit } = pendingToast.current;
      const dm = res.plan.gross_margin - before.gross_margin;
      const dv = res.plan.value - before.value;
      const moved = res.plan.picks.flatMap((x) => {
        const was = before.picks.find((y) => y.lot === x.lot);
        return was && was.buyer !== x.buyer ? [`${lotBy[x.lot]?.name}: ${was.buyer ? colBy[was.buyer]?.name : "nobody"} to ${x.buyer ? colBy[x.buyer]?.name : "nobody"}`] : [];
      });
      setToast({
        head, ms: planEdit ? null : res.meta.rank_ms, moved,
        delta: dm || dv ? `Paper margin ${signed(dm)}, fit-weighted value ${signed(dv)}.` : null,
        added: planEdit ? [] : added.map((x) => lotBy[x]?.name), removed: planEdit ? [] : removed.map((x) => lotBy[x]?.name),
      });
      pendingToast.current = null;
      clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setToast(null), 8000);
    }
    const t = setTimeout(() => setFlash(new Set()), 1600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [res, lotBy, colBy]);

  const togglePlan = useCallback((id: string) => {
    const leaving = plan.includes(id);
    pendingToast.current = { head: `${leaving ? "Removed" : "Added"} ${lotBy[id]?.name}.`, planEdit: true };
    setPlan((cur) => (leaving ? cur.filter((x) => x !== id) : [...cur, id]));
  }, [plan, lotBy]);

  const startDrag = useCallback((e: DragEvent<HTMLElement>, id: string) => {
    e.dataTransfer.setData(LOT_DRAG, id);
    e.dataTransfer.effectAllowed = "copy";
    // drag the photo at the size it will have in the parcel, not the whole card
    const photo = e.currentTarget.querySelector("img");
    if (photo?.naturalHeight) {
      const dpr = window.devicePixelRatio || 1;
      const w = Math.round(TILE_H * (photo.naturalWidth / photo.naturalHeight));
      const ghost = document.createElement("canvas");
      ghost.width = w * dpr;
      ghost.height = TILE_H * dpr;
      ghost.style.cssText = `position:fixed;top:-${TILE_H * 2}px;left:0;width:${w}px;height:${TILE_H}px`;
      ghost.getContext("2d")?.drawImage(photo, 0, 0, ghost.width, ghost.height);
      document.body.append(ghost);
      e.dataTransfer.setDragImage(ghost, w / 2, TILE_H / 2);
      setTimeout(() => ghost.remove());
    }
    // changing the page during dragstart can cancel the drag in Chrome
    setTimeout(() => setDragLot(id));
  }, []);

  const endDrag = useCallback(() => {
    setDragLot(null);
    setOverParcel(false);
  }, []);

  // accepted on enter as well as over, so a quick flick that lets go at once still drops
  const acceptLot = useCallback((e: DragEvent<HTMLElement>) => {
    if (!e.dataTransfer.types.includes(LOT_DRAG)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setOverParcel(true);
  }, []);

  const dropOnParcel = useCallback((e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    const id = e.dataTransfer.getData(LOT_DRAG);
    endDrag();
    if (id && !plan.includes(id)) togglePlan(id);
  }, [plan, togglePlan, endDrag]);

  const addAll = useCallback((ids: string[]) => {
    pendingToast.current = { head: `Added ${ids.length} suggested ${ids.length > 1 ? "lots" : "lot"} to your parcel.`, planEdit: true };
    setPlan((cur) => [...cur, ...ids]);
  }, []);

  const clearPlan = useCallback(() => {
    pendingToast.current = { head: "Cleared your parcel.", planEdit: true };
    setPlan([]);
  }, []);

  const revealOffers = useCallback(() => {
    const next = offers.slice(revealed, revealed + OFFERS_PER_REVEAL);
    if (!next.length) return;
    pendingToast.current = { head: `${next.length} new ${next.length > 1 ? "offers" : "offer"} on the radar: ${next.map((l) => l.name).join(", ")}.`, planEdit: false };
    setRevealed((n) => n + next.length);
  }, [offers, revealed]);

  const addSignal = useCallback((cid: string, s: Signal, label: string) => {
    pendingToast.current = { head: `${colBy[cid]?.name}: ${label}.`, planEdit: false };
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

  const p = res?.plan;
  const suggested = res?.portfolio;
  const next = res?.next;
  const trophyAsk = Math.max(...radarLots.map((l) => l.ask));
  const poolSize = radarLots.length;
  const editCount = Object.values(signals).reduce((a, b) => a + b.length, 0) + passes.length + revealed;
  const buyersIn = (x?: Plan) => new Set((x?.picks ?? []).map((y) => y.buyer).filter(Boolean)).size;
  const left = budget - (p?.spent ?? 0);
  const dragged = dragLot ? lotBy[dragLot] : null;
  const placedTo = (cid: string) => (p?.picks ?? []).filter((x) => x.buyer === cid);
  const stretchOf = (lot: string, cid: string) => res?.demand[lot]?.find((r) => r.collector === cid)?.stretch ?? 0;
  const timesLargest = (lot: string, cid: string) => res?.demand[lot]?.find((r) => r.collector === cid)?.vs_largest ?? 0;
  const row = (x: Pick_, action: string, title: string, act: () => void, quiet = false) => (
    <div key={x.lot} className="pick-row">
      <button className="pick" onClick={() => setLotOpen(x.lot)}>
        <img src={lotBy[x.lot]?.image} alt="" />
        <div style={{ minWidth: 0 }}>
          <div className="n" title={lotBy[x.lot]?.name}>{lotBy[x.lot]?.name}</div>
          <div className="b">{x.buyer ? <>Call <span className="who">{colBy[x.buyer]?.name}</span>, ranks it #{x.rank} of {poolSize}{stretchOf(x.lot, x.buyer) > 0 && <span className="am">, {usd(stretchOf(x.lot, x.buyer))} over capacity</span>}{timesLargest(x.lot, x.buyer) > 1 && <span>, {timesLargest(x.lot, x.buyer).toFixed(1)}× their largest purchase</span>}</> : <span className="am">No collector in range</span>}</div>
        </div>
        <div className="r">{usd(x.ask)}<div>est. {usd(x.resale)}</div></div>
      </button>
      <button className={`buy ${quiet ? "quiet" : ""}`} title={title} onClick={act}>{action}</button>
    </div>
  );

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
          <div className="budget-sub">{p?.picks.length ? (left >= 0 ? `${usd(p.spent)} in parcel, ${usd(left)} left` : `${usd(p.spent)} in parcel, ${usd(-left)} over`) : "Available, not a target to spend"}</div>
          <input id="budget" className="range" type="range" min={10000} max={200000} step={1000} value={budget} style={fill(budget, 10000, 200000)}
            onChange={(e) => setBudget(+e.target.value)} />
        </div>
        <div className={`band-alloc ${dragged ? "droppable" : ""} ${overParcel ? "over" : ""}`}
          onDragEnter={acceptLot}
          onDragOver={acceptLot}
          onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOverParcel(false); }}
          onDrop={dropOnParcel}>
          <div className="alloc-head">
            <div className="alloc-line" aria-live="polite">
              {!p ? "Reading the book…"
                : dragged ? <>Drop to add <b>{dragged.name}</b>, {usd(dragged.ask)}: {left - dragged.ask >= 0 ? `${usd(left - dragged.ask)} would be left.` : <span className="red">{usd(dragged.ask - left)} over your capital.</span>}</>
                : focus ? (() => {
                  const mine = placedTo(focus);
                  return mine.length
                    ? <><b>{colBy[focus]?.name}</b> would take {mine.length} {mine.length > 1 ? "pieces" : "piece"}, <b>{usd(mine.reduce((a, x) => a + x.ask, 0))}</b> of your parcel.</>
                    : <>Nothing in your parcel goes to <b>{colBy[focus]?.name}</b> yet.</>;
                })()
                : p.picks.length === 0 ? <><b>Your parcel is empty.</b> The suggestion is {usd(suggested?.spent ?? 0)} on {suggested?.picks.length ?? 0} lots.</>
                : left >= 0 ? <><b>Your parcel:</b> {usd(p.spent)} on {p.picks.length} of {poolSize} lots, {usd(left)} still available.</>
                : <><b>Your parcel:</b> {usd(p.spent)} on {p.picks.length} of {poolSize} lots, <span className="red">{usd(-left)} over your capital.</span></>}
            </div>
            <span className="alloc-key">Bar: share of budget</span>
          </div>
          <Allocation picks={p?.picks ?? []} budget={Math.max(budget, p?.spent ?? 0) || 1} spent={p?.spent ?? 0} lotBy={lotBy} colBy={colBy} focus={focus} flash={flash} incoming={dragged?.ask ?? 0}
            open={(id) => { setCollectorOpen(null); setCredits(false); setLotOpen(id); }} />
        </div>
        <div className="band-ledger">
          <Line label="Paper margin" sub={`Resale minus ask. Suggested: ${suggested ? usd(suggested.gross_margin) : "…"}`} value={p ? usd(p.gross_margin) : "…"} />
          <Line label="Fit-weighted value" sub={`Margin × fit, less holding. Suggested: ${suggested ? usd(suggested.value) : "…"}`} value={p ? usd(p.value) : "…"} />
          <Line label="Collectors placed" sub={`In their top ${settings.max_rank}. Suggested: ${buyersIn(suggested)}`} value={p ? `${buyersIn(p)} of ${book.collectors.length}` : "…"} />
        </div>
      </div>

      {err && <div className="pad red">{err}</div>}

      <div className="main">
        <div className="col">
          <div className="head"><h2>Collector book</h2><span className="aside">{book.collectors.length} collectors</span></div>
          <div className="scroll collectors-scroll">
            {book.collectors.map((c) => {
              const placed = placedTo(c.id);
              const waiting = (next?.picks ?? []).filter((x) => x.buyer === c.id);
              const live = signals[c.id]?.length ?? 0;
              return (
                <button key={c.id} className={`collector ${focus === c.id ? "on" : ""}`}
                  onMouseEnter={() => setFocus(c.id)} onMouseLeave={() => setFocus(null)} onFocus={() => setFocus(c.id)} onBlur={() => setFocus(null)}
                  onClick={() => setCollectorOpen(c.id)}>
                  <div className="c-name">{c.name}</div>
                  <div className="c-cap">{usdK(c.capacity)}</div>
                  <div className="c-city">{live > 0 ? <span className="am">{live} {live > 1 ? "signals" : "signal"} today</span> : c.city}</div>
                  <div className="c-placed" aria-label={placed.length + waiting.length ? `${placed.length} in your parcel, ${waiting.length} suggested` : undefined}>
                    {placed.map((x) => <img key={x.lot} src={lotBy[x.lot]?.image} alt="" title={`In your parcel: ${lotBy[x.lot]?.name}`} />)}
                    {waiting.map((x) => <img key={x.lot} className="suggested" src={lotBy[x.lot]?.image} alt="" title={`Suggested: ${lotBy[x.lot]?.name}`} />)}
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
            <span className="aside">{poolSize} incoming {poolSize === 1 ? "lot" : "lots"}{plan.length > 0 ? `, ${plan.length} in your parcel` : ""}</span>
            {revealed < offers.length && <button className="link" title="Reveals offers already in the catalog, so their rankings are real but their arrival is staged" onClick={revealOffers}>Simulate new offers ({offers.length - revealed} left)</button>}
            <span className="aside push">
              {focus ? `Lit by ${colBy[focus]?.name}'s ranking, brightest first` : <><span className="for-mouse">Drag lots up to your parcel</span><span className="for-touch">Tap a lot to add it to your parcel</span></>}
            </span>
          </div>
          <div className="scroll">
            <div className="lots">
              {radarLots.map((l) => {
                const pick = planned[l.id] ?? nextUp[l.id];
                const inPlan = plan.includes(l.id);
                const isSuggested = !inPlan && !!nextUp[l.id];
                const isNew = newOffers.some((x) => x.id === l.id);
                const best = res?.demand[l.id]?.find((x) => x.rank <= settings.max_rank && x.affordable && !x.passed);
                const d = focus ? res?.demand[l.id]?.find((x) => x.collector === focus) : null;
                const lit = d ? ({ "--b": 0.14 + 0.86 * d.fit, "--s": 0.35 + 0.65 * d.fit }) as CSSProperties : undefined;
                return (
                  <div key={l.id} role="button" tabIndex={0} className={`lot ${pick ? "in" : ""} ${isSuggested && !focus ? "sug" : ""} ${dragLot === l.id ? "dragging" : ""} ${flash.has(l.id) ? "flash" : ""}`} style={lit} title={l.name}
                    draggable={!inPlan} onDragStart={(e) => startDrag(e, l.id)} onDragEnd={endDrag}
                    onClick={() => setLotOpen(l.id)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setLotOpen(l.id); } }}>
                    <div className="thumb">
                      <img src={l.image} alt="" loading="lazy" draggable={false} />
                      {d ? <span className={`plate rank ${d.rank <= 3 ? "top" : d.rank <= settings.max_rank ? "near" : ""}`}>#{d.rank}</span>
                        : isNew ? <span className="plate trophy">New offer</span>
                        : l.ask === trophyAsk ? <span className="plate trophy">Trophy</span> : null}
                      {inPlan ? <span className="mark held">In parcel</span> : isSuggested ? <span className="mark sug">Suggested</span> : null}
                    </div>
                    <div className="ticket">
                      <div className="t-name"><span className="t-no">{l.lot_no}</span>{l.name}</div>
                      <div className="t-px"><span>{usd(l.ask)}</span><span className="est">est. {usd(l.resale)}</span></div>
                      <div className="t-to">
                        {pick?.buyer ? <>For <b>{colBy[pick.buyer]?.name}</b>, #{pick.rank}</>
                          : inPlan ? <span className="am">No collector in range</span>
                          : best ? <>Best match {colBy[best.collector]?.name}, #{best.rank}</>
                          : "No collector in range"}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            {res && (
              <div className="lower">
                <div>
                  <div className="head flat"><h3>What the next dollar buys</h3></div>
                  <Frontier data={res.frontier} budget={budget} />
                </div>
                <div>
                  <div className="head flat"><h3>Same budget, other ways to choose</h3></div>
                  <table>
                    <thead><tr><th>Strategy</th><th>Pieces</th><th>Paper margin</th><th>Fit value</th><th>Unplaced</th></tr></thead>
                    <tbody>
                      {res.compare.map((c) => (
                        <tr key={c.key} className={c.key === "plan" ? "hl" : ""} title={c.note}>
                          <td className="text">{c.name}<div className="sub">{c.note}</div></td>
                          <td>{c.pieces}</td><td>{usdK(c.gross_margin)}</td><td>{usdK(c.value)}</td>
                          <td>{c.unplaced_capital ? usdK(c.unplaced_capital) : "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="pad note">All are scored by the same rules and BehaviorGPT fit, so this compares choices under this tool's assumptions. It is not a forecast of sales.</div>
                </div>
              </div>
            )}
            {res && <Inventory holdings={res.holdings} lotBy={lotBy} colBy={colBy} maxRank={settings.max_rank} />}
          </div>
        </div>

        <div className="col col-desk">
          <div className="head">
            <h2>Capital Desk</h2>
            <span className="aside">What you intend to buy</span>
            <button className="link push" onClick={() => setShowSettings((s) => !s)}>{showSettings ? "Hide assumptions" : "Assumptions"}</button>
          </div>
          {editCount > 0 && (
            <div className="desk-tools">
              <button className="link" onClick={() => { setSignals({}); setPasses([]); setRevealed(0); setPlan((cur) => cur.filter((id) => opening.some((l) => l.id === id))); }}>Reset {editCount} {editCount > 1 ? "edits" : "edit"}</button>
            </div>
          )}
          {showSettings && <Assumptions s={settings} set={setSettings} />}
          <div className="scroll">
            <div className="head flat">
              <h3>Your parcel</h3>
              {plan.length > 0 && <button className="link" onClick={clearPlan}>Clear</button>}
              <span className={`aside push ${left < 0 ? "red" : ""}`}>{usd(p?.spent ?? 0)} of {usd(budget)}</span>
            </div>
            {p?.picks.length === 0 && <div className="pad muted">Nothing in your parcel yet. Drag lots from the Deal Radar to the parcel at the top, or add from the suggestion below.</div>}
            {p?.picks.map((x) => row(x, "Remove", "Take this out of your parcel", () => togglePlan(x.lot), true))}
            {p && p.picks.length > 0 && (
              <div className="total">
                <span>Total, {p.picks.length} {p.picks.length > 1 ? "pieces" : "piece"}</span>
                <span className="r">{usd(p.spent)}<div>est. {usd(p.spent + p.gross_margin)}</div></span>
              </div>
            )}
            <div className="head flat">
              <h3>{plan.length ? "Suggested next" : "Suggested parcel"}</h3>
              {!!next?.picks.length && <button className="link" onClick={() => addAll(next.picks.map((x) => x.lot))}>Add all {next.picks.length}</button>}
              <span className="aside push">{usd(Math.max(0, left))} available</span>
            </div>
            {next?.picks.length === 0 && <div className="pad muted">{left <= 0 ? "No capital left to suggest anything." : "Nothing else clears the bar. That's a fine answer: the capital stays available."}</div>}
            {next?.picks.map((x) => row(x, "Add", "Add this to your parcel", () => togglePlan(x.lot)))}
            {next && next.picks.length > 0 && (
              <div className="total">
                <span>{next.picks.length} {next.picks.length > 1 ? "pieces" : "piece"}, fit-weighted value {usd(next.value)}</span>
                <span className="r">{usd(next.spent)}<div>est. {usd(next.spent + next.gross_margin)}</div></span>
              </div>
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
        <LotDrawer lot={lotBy[lotOpen]} res={res} colBy={colBy} total={poolSize} passes={passes} togglePass={togglePass} inPlan={plan.includes(lotOpen)} togglePlan={togglePlan}
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
          <div>{toast.head}{toast.ms !== null && ` Re-ranked in ${toast.ms} ms.`}</div>
          {toast.delta && <div className="note">{toast.delta}</div>}
          {toast.moved.map((n) => <div className="note" key={n}>{n}</div>)}
          {toast.added.map((n) => <div className="tl" key={n}><span className="in">In</span><span>Suggestion: {n}</span></div>)}
          {toast.removed.map((n) => <div className="tl" key={n}><span className="out">Out</span><span className="ink2">Suggestion: {n}</span></div>)}
          {toast.ms !== null && toast.added.length + toast.removed.length === 0 && <div className="note">The suggestion holds.</div>}
        </div>
      )}
    </div>
  );
}

/** The collector each radar card names: its parcel or suggested buyer, otherwise its best match. */
function buyersOnScreen(r: Result, maxRank: number): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [lot, rows] of Object.entries(r.demand)) {
    const best = rows.find((x) => x.rank <= maxRank && x.affordable && !x.passed);
    if (best) out[lot] = best.collector;
  }
  for (const x of [...r.next.picks, ...r.plan.picks]) if (x.buyer) out[x.lot] = x.buyer;
  return out;
}

function Line({ label, sub, value, tone }: { label: string; sub?: string; value: string; tone?: string }) {
  return (
    <div className="line">
      <div className="line-l"><div>{label}</div><div>{sub}</div></div>
      <div className={`line-v ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

function Allocation({ picks, budget, spent, lotBy, colBy, focus, flash, incoming, open }: {
  picks: Pick_[]; budget: number; spent: number; lotBy: Record<string, Piece>; colBy: Record<string, Collector>; focus: string | null; flash: Set<string>; incoming: number; open: (id: string) => void;
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
      <div className="share" role="img" aria-label={`${usd(spent)} of ${usd(budget)} in the parcel across ${picks.length} lots, ${usd(dry)} left unspent`}>
        {ordered.map((x) => (
          <i key={x.lot} className={`${dimmed(x)} ${hot === x.lot ? "hot" : ""}`} style={{ flexBasis: `${(x.ask / budget) * 100}%` }}
            title={`${lotBy[x.lot]?.name}: ${usd(x.ask)}, ${Math.round((x.ask / budget) * 100)}% of the budget`} />
        ))}
        {incoming > 0 && <i className={`incoming ${incoming > dry ? "over" : ""}`} style={{ flexBasis: `${(incoming / budget) * 100}%` }} />}
      </div>
      <div className="tiles" ref={row} role="group" aria-label="Your parcel"
        onWheel={(e) => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) e.currentTarget.scrollLeft += e.deltaY; }}>
        {ordered.length === 0 && <div className="tiles-empty"><span className="for-mouse">Drag lots here from the Deal Radar</span><span className="for-touch">Tap a lot on the Deal Radar to add it here</span></div>}
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

function LotDrawer({ lot, res, colBy, total, passes, togglePass, inPlan, togglePlan, maxRank, onClose, logView }: {
  lot: Piece; res: Result; colBy: Record<string, Collector>; total: number; passes: [string, string][];
  togglePass: (l: string, c: string) => void; inPlan: boolean; togglePlan: (id: string) => void; maxRank: number; onClose: () => void; logView: (cid: string) => void;
}) {
  const pick = res.plan.picks.find((x) => x.lot === lot.id) ?? res.next.picks.find((x) => x.lot === lot.id);
  const rows = res.demand[lot.id] ?? [];
  const eligible = rows.filter((r) => r.rank <= maxRank && r.affordable && !r.passed);
  const taken = new Set([...res.plan.picks, ...res.next.picks].map((x) => x.buyer));
  const nearest = rows.filter((r) => r.rank <= maxRank && !r.affordable && !r.passed).sort((a, b) => a.over_by - b.over_by)[0];
  const noBuyer = eligible.length === 0
    ? nearest
      ? `No collector who ranks this within #${maxRank} has the capacity for ${usd(lot.resale)}. Closest: ${colBy[nearest.collector]?.name}, over by ${usd(nearest.over_by)}.`
      : `No collector ranks this within #${maxRank}.`
    : eligible.every((r) => taken.has(r.collector))
      ? `Everyone in range for it (${eligible.slice(0, 3).map((r) => colBy[r.collector]?.name).join(", ")}) already has a piece placed.`
      : "Collectors are in range, but other lots earn more fit-weighted value at this budget. Add it to see what it does to your parcel.";
  const tied = (inPlan ? res.plan : res.next).ties?.[lot.id] ?? [];
  const tieNames = pick?.buyer ? [pick.buyer, ...tied].map((c) => colBy[c]?.name) : [];
  const reason = inPlan
    ? pick?.buyer ? `In your parcel, placed with ${colBy[pick.buyer]?.name}, who ranks it #${pick.rank} of ${total}.` : `In your parcel with no buyer. ${noBuyer} It takes the holding charge until someone is found.`
    : pick?.buyer ? `Suggested for ${colBy[pick.buyer]?.name}, who ranks it #${pick.rank} of ${total}.` : noBuyer;
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
          {pick?.buyer && tied.length > 0 && (
            <div className="tie">
              {tieNames.slice(0, -1).join(", ")} and {tieNames[tieNames.length - 1]} tie for this lot. {inPlan ? "Your parcel" : "The suggestion"} scores the same with {tied.length > 1 ? "any of them" : "either"}, so the choice of {colBy[pick.buyer]?.name} is arbitrary.
            </div>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <button className={`btn ${inPlan ? "" : "primary"}`} onClick={() => togglePlan(lot.id)}>{inPlan ? "Remove from parcel" : "Add to parcel"}</button>
          </div>
        </div>
        <div className="dsec flush">
          <h3>Who ranks it where</h3>
          <table>
            <thead><tr><th>Collector</th><th className="rank-lead" title="The rank used to choose buyers: Activity and Purchases blended, then adjusted for how much more this collector ranks the lot than other collectors do">Overall</th><th title="BehaviorGPT, reading everything they did in order: views, searches and purchases">Activity</th><th title="BehaviorGPT, reading only what they bought">Purchases</th><th title="Simple overlap in form, era, style, stone and metal. Not BehaviorGPT and not used to choose buyers">Tag match</th><th></th></tr></thead>
            <tbody>
              {rows.slice(0, 10).map((r) => {
                const passed = passes.some(([l, c]) => l === lot.id && c === r.collector);
                return (
                  <tr key={r.collector} className={`${pick?.buyer === r.collector || tied.includes(r.collector) ? "hl" : ""} ${passed ? "dim" : ""}`}>
                    <td className="text">{colBy[r.collector]?.name}{!r.affordable && <span className="muted">, {usd(r.over_by)} past the limit</span>}{r.stretch > 0 && <span className="am">, {usd(r.stretch)} over capacity</span>}{r.vs_largest !== null && <span className="muted">, {r.vs_largest.toFixed(1)}× largest purchase</span>}</td>
                    <td className="rank-lead">#{r.rank}</td><td>#{r.rank_full}</td><td>#{r.rank_orders}</td>
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
          <div className="pad note">Amber Tag match: tag matching and BehaviorGPT's Activity rank disagree by 8+ places. That disagreement could be insight or noise, so treat it as a question to ask the collector. “Viewed” re-ranks that collector live. “Passed” only removes them as a buyer for this lot.</div>
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

const STOCK_VIEWS = [["all", "All"], ["live", "In range"], ["thin", "Thin"], ["stale", "Stale"]] as const;

function Inventory({ holdings, lotBy, colBy, maxRank }: {
  holdings: Holding[]; lotBy: Record<string, Piece>; colBy: Record<string, Collector>; maxRank: number;
}) {
  const [show, setShow] = useState<(typeof STOCK_VIEWS)[number][0]>("all");
  const count = (s: string) => (s === "all" ? holdings.length : holdings.filter((h) => h.status === s).length);
  const rows = holdings.filter((h) => show === "all" || h.status === show)
    .sort((a, b) => b.reach - a.reach || (lotBy[b.id]?.ask ?? 0) - (lotBy[a.id]?.ask ?? 0));
  const firstName = (id: string) => colBy[id]?.name.split(" ")[0];
  return (
    <div className="section-top table-scroll">
      <div className="head flat">
        <h3>Your inventory</h3>
        <span className="aside">{holdings.length} pieces, {usd(holdings.reduce((s, h) => s + (lotBy[h.id]?.ask ?? 0), 0))} at simulated cost</span>
        <span className="segctl push">
          {STOCK_VIEWS.map(([k, label]) => (
            <button key={k} className={show === k ? "on" : ""} aria-pressed={show === k} onClick={() => setShow(k)}>{label} {count(k)}</button>
          ))}
        </span>
      </div>
      <div className="stock-scroll">
        <table>
          <thead><tr><th>Piece</th><th>Cost basis</th><th title={`Collectors who rank this within #${maxRank} of your stock`}>In range</th><th>Closest collector</th><th>Viewed by</th><th>Status</th></tr></thead>
          <tbody>
            {rows.map((h) => (
              <tr key={h.id}>
                <td className="text"><span className="stock-piece"><img src={lotBy[h.id]?.image} alt="" loading="lazy" />{lotBy[h.id]?.name}</span></td>
                <td>{usd(lotBy[h.id]?.ask ?? 0)}</td>
                <td>{h.reach}</td>
                <td className="text" style={{ textAlign: "right" }}>{colBy[h.best[0]?.collector]?.name}, #{h.best[0]?.rank}</td>
                <td className="text" style={{ textAlign: "right" }} title={h.viewed_by.map((c) => colBy[c]?.name).join(", ")}>
                  {h.viewed_by.length === 0 ? <span className="muted">–</span> : <>{h.viewed_by.slice(0, 2).map(firstName).join(", ")}{h.viewed_by.length > 2 && <span className="muted"> +{h.viewed_by.length - 2}</span>}</>}
                </td>
                <td className={h.status === "live" ? "em" : h.status === "thin" ? "am" : "red"}>{h.status === "stale" ? "Stale" : h.status === "thin" ? "Thin: one collector" : "In range"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pad note">Everything viewed but never bought is still yours. Ranked only against your own stock. A piece ranks higher for someone who has viewed it, so "Viewed by" is a lead, not independent demand. Inventory does not change your parcel or the suggestion. Pieces, costs and views are invented.</div>
    </div>
  );
}

function CollectorDrawer({ c, res, lotBy, signals, tolerance, onClose, addSearch }: {
  c: Collector; res: Result; lotBy: Record<string, Piece>; signals: Signal[]; tolerance: number; onClose: () => void; addSearch: (q: string) => void;
}) {
  const [q, setQ] = useState("");
  const viewed = (id: string) => res.holdings.find((h) => h.id === id)?.viewed_by.includes(c.id);
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
          <h3>From your inventory, by their ranking</h3>
          {res.in_stock[c.id]?.map((id) => (
            <div className="event" key={id} style={{ gridTemplateColumns: "30px minmax(0,1fr)" }}>
              <img src={lotBy[id]?.image} alt="" /><span>{lotBy[id]?.name}{viewed(id) && <span className="am"> · viewed</span>}</span>
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
