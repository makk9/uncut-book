import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Credit = { title: string; author: string; license: string; license_url: string; source: string; landing_url: string };
type Piece = {
  id: string; lot_no: number; name: string; form: string; era: string; style: string; stones: string[]; metals: string[];
  ask: number; resale: number; image: string; description: string; condition?: string; supplier?: string; credit: Credit;
};
type TimelineEvent = { type: string; q?: string; id?: string; name?: string; image?: string };
type Collector = {
  id: string; name: string; city: string; blurb: string; capacity: number; capacity_note: string;
  lifetime_spend: number; orders: number; timeline: TimelineEvent[]; event_count: number;
};
type Book = { lots: Piece[]; holdings: Piece[]; collectors: Collector[]; live: boolean };
type Pick_ = { lot: string; ask: number; resale: number; buyer: string | null; rank: number | null; fit: number; value: number };
type Demand = { collector: string; rank: number; rank_full: number; rank_orders: number; rank_tags: number; fit: number; affordable: boolean; passed: boolean };
type Result = {
  portfolio: { picks: Pick_[]; spent: number; budget: number; unspent: number; gross_margin: number; value: number; unplaced_capital: number };
  stress: { collector: string; value: number; value_lost: number; unplaced_capital: number; unplaced: string[] }[];
  compare: { key: string; name: string; note: string; lots: string[]; spent: number; gross_margin: number; value: number; unplaced_capital: number; pieces: number; worst_loss: number }[];
  frontier: { budget: number; value: number; spent: number; pieces: number }[];
  demand: Record<string, Demand[]>;
  holdings: { id: string; best: { collector: string; rank: number }[]; reach: number; status: string }[];
  drift: Record<string, { gap: number; rising: string[]; fading: string[] }>;
  meta: { source: string; rank_ms: number; solve_ms: number; calls: number };
};
type Signal = { type: "search" | "view"; q?: string; id?: string };
type Settings = { fit_decay: number; holding_penalty: number; max_rank: number; slots: number; recency: number };
type WhatIf = { feasible: boolean; reason?: string; already_in?: boolean; value_delta?: number; margin_delta?: number; displaced?: string[]; added?: string[]; buyer?: string | null; rank?: number | null };

const usd = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
const usdK = (n: number) => (Math.abs(n) >= 1000 ? `$${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k` : `$${Math.round(n)}`);
const signed = (n: number) => `${n >= 0 ? "+" : "−"}${usd(Math.abs(n))}`;
const MODES = [
  { key: "value", label: "Max value", res: 0 },
  { key: "balanced", label: "Balanced", res: 0.5 },
  { key: "hardened", label: "Buyer-proof", res: 0.9 },
];
const DEFAULTS: Settings = { fit_decay: 4, holding_penalty: 0.15, max_rank: 8, slots: 2, recency: 0.6 };

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
  const [toast, setToast] = useState<string | null>(null);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const prevPicks = useRef<Set<string> | null>(null);
  const pendingToast = useRef<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    fetch("/api/book").then((r) => r.json()).then(setBook).catch(() => setErr("Could not load the book."));
  }, []);

  const body = useMemo(() => ({
    budget, ...settings, resilience: MODES.find((m) => m.key === mode)!.res, signals, passes,
  }), [budget, settings, mode, signals, passes]);

  useEffect(() => {
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
  }, [body]);

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
    const removed = [...prev].filter((x) => !now.has(x));
    setFlash(new Set(added));
    if (pendingToast.current) {
      const change = added.length || removed.length
        ? [...added.map((x) => `+ ${lotBy[x]?.name}`), ...removed.map((x) => `− ${lotBy[x]?.name}`)].join("   ")
        : "Portfolio holds.";
      setToast(`${pendingToast.current} Re-ranked in ${res.meta.rank_ms} ms. ${change}`);
      pendingToast.current = null;
      setTimeout(() => setToast(null), 8000);
    }
    const t = setTimeout(() => setFlash(new Set()), 1600);
    return () => clearTimeout(t);
  }, [res, lotBy]);

  const addSignal = useCallback((cid: string, s: Signal, label: string) => {
    pendingToast.current = `${colBy[cid]?.name}: ${label}.`;
    setSignals((cur) => ({ ...cur, [cid]: [...(cur[cid] ?? []), s] }));
  }, [colBy]);

  const togglePass = useCallback((lot: string, cid: string) => {
    setPasses((cur) => (cur.some(([l, c]) => l === lot && c === cid) ? cur.filter(([l, c]) => !(l === lot && c === cid)) : [...cur, [lot, cid]]));
  }, []);

  if (!book) return <div className="pad muted">{err ?? "Opening the book…"}</div>;

  const p = res?.portfolio;
  const book_ = res?.compare.find((c) => c.key === "book");
  const trophyAsk = Math.max(...book.lots.map((l) => l.ask));
  const signalCount = Object.values(signals).reduce((a, b) => a + b.length, 0);
  const placedTo = (cid: string) => (p?.picks ?? []).filter((x) => x.buyer === cid);

  return (
    <div className="app">
      <div className="bar">
        <span className="logo">THE BOOK</span>
        <span className="tag">Know your buyers. Own the right stones.</span>
        <span className="spacer" />
        <span className="pill">
          <span className={`dot ${res?.meta.source === "snapshot" ? "off" : ""} ${busy ? "busy" : ""}`} />
          {res ? `BehaviorGPT ${res.meta.source} · ${res.meta.calls} rankings · ${res.meta.rank_ms} ms · solve ${res.meta.solve_ms} ms` : "Reading the book…"}
        </span>
        <span className="pill demo">REPRESENTATIVE DATA, NOT MARKET PRICES</span>
      </div>

      <div className="strip">
        <div className="cell">
          <div className="up muted">Acquisition budget</div>
          <div className="big budget">{usd(budget)}</div>
          <input className="slider" aria-label="Acquisition budget" type="range" min={10000} max={200000} step={1000} value={budget}
            onChange={(e) => setBudget(+e.target.value)} />
        </div>
        <Stat label="Deployed" value={p ? usd(p.spent) : "…"} sub={p ? `${usd(p.unspent)} kept dry` : ""} />
        <Stat label="Pieces" value={p ? String(p.picks.length) : "…"} sub={`of ${book.lots.length} lots offered`} />
        <Stat label="Paper margin" value={p ? usd(p.gross_margin) : "…"} sub="Your resale estimates minus ask" />
        <Stat label="Fit-weighted value" value={p ? usd(p.value) : "…"} sub="Margin × rank fit, less holding" tone="em" />
        <Stat label="If one buyer walks" value={book_ ? `−${usd(book_.worst_loss)}` : "…"} sub={res?.stress[0] ? `Worst case: ${colBy[res.stress[0].collector]?.name}` : ""} tone="am" />
      </div>

      {err && <div className="pad red">{err}</div>}

      <div className="main">
        <div className="col">
          <div className="head"><span className="up">Collector book</span><span className="muted num">{book.collectors.length}</span></div>
          <div className="scroll collectors-scroll">
            {book.collectors.map((c) => {
              const placed = placedTo(c.id);
              const gap = res?.drift[c.id]?.gap ?? 0;
              const live = signals[c.id]?.length ?? 0;
              return (
                <button key={c.id} className={`collector ${focus === c.id ? "on" : ""}`}
                  onMouseEnter={() => setFocus(c.id)} onMouseLeave={() => setFocus(null)} onFocus={() => setFocus(c.id)}
                  onClick={() => setCollectorOpen(c.id)}>
                  <div className="c-top"><span>{c.name}</span><span className="num ink2">{usdK(c.capacity)}</span></div>
                  <div className="c-meta">
                    <span>{c.city}</span>
                    <span>
                      {live > 0 && <span className="chip a">{live} signal{live > 1 ? "s" : ""}</span>}{" "}
                      {gap >= 5 && <span className="chip n" title="Recent behavior ranks this batch differently from what they have bought">drifting</span>}{" "}
                      {placed.length > 0 && <span className="chip g">{placed.length} placed</span>}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
          <div className="pad note">Hover a collector to see the batch through their ranking. Click to log a signal.</div>
        </div>

        <div className="col">
          <div className="head">
            <span className="up">Incoming batch · {book.lots.length} lots</span>
            <span className="muted" style={{ fontSize: 11 }}>
              {focus ? `Numbers show ${colBy[focus]?.name}'s ranking` : "Green outline: in the portfolio"}
            </span>
          </div>
          <div className="scroll">
            <div className="lots">
              {book.lots.map((l) => {
                const pick = picks[l.id];
                const d = focus ? res?.demand[l.id]?.find((x) => x.collector === focus) : null;
                return (
                  <button key={l.id} className={`lot ${pick ? "in" : ""} ${flash.has(l.id) ? "flash" : ""}`} onClick={() => setLotOpen(l.id)}>
                    <div className="thumb">
                      <img src={l.image} alt={l.name} loading="lazy" />
                      <span className="badge chip n">{String(l.lot_no).padStart(2, "0")}</span>
                      {d ? <span className={`badge-r chip ${d.rank <= 3 ? "g" : d.rank <= settings.max_rank ? "a" : "n"}`}>#{d.rank}</span>
                        : l.ask === trophyAsk ? <span className="badge-r chip a">TROPHY</span> : null}
                    </div>
                    <div className="body">
                      <div className="name">{l.name}</div>
                      <div className="px"><span>{usd(l.ask)}</span><span className="muted">→ {usd(l.resale)}</span></div>
                      <div className="to">{pick ? (pick.buyer ? <>for <b>{colBy[pick.buyer]?.name}</b> · #{pick.rank}</> : <span className="am">no buyer placed</span>) : "pass"}</div>
                    </div>
                  </button>
                );
              })}
            </div>
            {res && (
              <div className="lower">
                <div>
                  <div className="head"><span className="up">What the next dollar buys</span></div>
                  <Frontier data={res.frontier} budget={budget} />
                </div>
                <div>
                  <div className="head"><span className="up">Same budget, other ways to choose</span></div>
                  <table>
                    <thead><tr><th>Strategy</th><th>Pieces</th><th>Paper margin</th><th>Fit value</th><th>Unplaced</th><th>One buyer walks</th></tr></thead>
                    <tbody>
                      {res.compare.map((c) => (
                        <tr key={c.key} className={c.key === "book" ? "hl" : ""} title={c.note}>
                          <td className="text">{c.name}<div className="muted" style={{ fontSize: 10.5 }}>{c.note}</div></td>
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
              <div>
                <div className="head"><span className="up">Your current inventory, read against the same collectors</span></div>
                <table>
                  <thead><tr><th>Piece</th><th>Cost basis</th><th>Collectors in range</th><th>Closest collector</th><th>Status</th></tr></thead>
                  <tbody>
                    {res.holdings.map((h) => (
                      <tr key={h.id}>
                        <td className="text">{lotBy[h.id]?.name}</td>
                        <td>{usd(lotBy[h.id]?.ask ?? 0)}</td>
                        <td>{h.reach}</td>
                        <td className="text" style={{ textAlign: "right" }}>{colBy[h.best[0]?.collector]?.name} · #{h.best[0]?.rank}</td>
                        <td><span className={`chip ${h.status === "live" ? "g" : h.status === "thin" ? "a" : "r"}`}>{h.status === "stale" ? "Stale: move it" : h.status === "thin" ? "Thin: one collector" : "In demand"}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <div className="col">
          <div className="head">
            <span className="up">Proposed acquisition</span>
            <button className="link" onClick={() => setShowSettings((s) => !s)}>{showSettings ? "Hide assumptions" : "Assumptions"}</button>
          </div>
          <div className="pad row" style={{ justifyContent: "space-between", borderBottom: "1px solid var(--line)" }}>
            <div className="seg" role="group" aria-label="Objective">
              {MODES.map((m) => <button key={m.key} className={mode === m.key ? "on" : ""} aria-pressed={mode === m.key} onClick={() => setMode(m.key)}>{m.label}</button>)}
            </div>
            {signalCount + passes.length > 0 && <button className="link" onClick={() => { setSignals({}); setPasses([]); }}>Reset {signalCount + passes.length} edit{signalCount + passes.length > 1 ? "s" : ""}</button>}
          </div>
          {showSettings && <Assumptions s={settings} set={setSettings} />}
          <div className="scroll">
            {p && (
              <div className="capbar" title={`${usd(p.spent)} of ${usd(budget)}`}>
                {p.picks.map((x) => <i key={x.lot} style={{ flexBasis: `${(x.ask / budget) * 100}%` }} />)}
              </div>
            )}
            {p?.picks.length === 0 && <div className="pad muted">Nothing clears the bar at this budget. Raise it or relax the assumptions.</div>}
            {p?.picks.map((x) => (
              <button key={x.lot} className="pick" onClick={() => setLotOpen(x.lot)}>
                <img src={lotBy[x.lot]?.image} alt="" />
                <div style={{ minWidth: 0 }}>
                  <div className="n">{lotBy[x.lot]?.name}</div>
                  <div className="b">{x.buyer ? <>Call <span className="em">{colBy[x.buyer]?.name}</span> · ranks it #{x.rank} of {book.lots.length}</> : <span className="am">No buyer placed</span>}</div>
                </div>
                <div className="r">{usd(x.ask)}<div className="muted">→ {usd(x.resale)}</div></div>
              </button>
            ))}
            {res && res.stress.length > 0 && (
              <>
                <div className="head" style={{ marginTop: 10 }}><span className="up">If this buyer walks</span><span className="muted" style={{ fontSize: 11 }}>portfolio is re-placed</span></div>
                <table>
                  <thead><tr><th>Buyer lost</th><th>Value lost</th><th>Left unplaced</th></tr></thead>
                  <tbody>
                    {res.stress.slice(0, 6).map((s) => (
                      <tr key={s.collector}><td className="text">{colBy[s.collector]?.name}</td><td>−{usd(s.value_lost)}</td><td>{s.unplaced_capital ? <span className="am">{usd(s.unplaced_capital)}</span> : "none"}</td></tr>
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
        <LotDrawer lot={lotBy[lotOpen]} res={res} colBy={colBy} body={body} total={book.lots.length} passes={passes} togglePass={togglePass} lotBy={lotBy}
          maxRank={settings.max_rank} onClose={() => setLotOpen(null)} logView={(cid) => addSignal(cid, { type: "view", id: lotOpen }, `looked at ${lotBy[lotOpen].name}`)} />
      )}
      {collectorOpen && colBy[collectorOpen] && res && (
        <CollectorDrawer c={colBy[collectorOpen]} res={res} lotBy={lotBy} signals={signals[collectorOpen] ?? []}
          onClose={() => setCollectorOpen(null)}
          addSearch={(q) => addSignal(collectorOpen, { type: "search", q }, `asked about “${q}”`)} />
      )}
      {credits && <Credits lots={Object.values(lotBy)} onClose={() => setCredits(false)} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="cell">
      <div className="up muted">{label}</div>
      <div className={`big ${tone ?? ""}`}>{value}</div>
      <div className="sub">{sub}</div>
    </div>
  );
}

function Assumptions({ s, set }: { s: Settings; set: (x: Settings) => void }) {
  const Row = (k: keyof Settings, label: string, min: number, max: number, step: number, fmt: (n: number) => string) => (
    <label key={k}>{label}: <span className="num">{fmt(s[k])}</span>
      <input type="range" min={min} max={max} step={step} value={s[k]} onChange={(e) => set({ ...s, [k]: +e.target.value })} />
    </label>
  );
  return (
    <div className="settings">
      {Row("recency", "Recent behavior vs purchases", 0, 1, 0.05, (n) => `${Math.round(n * 100)}/${Math.round((1 - n) * 100)}`)}
      {Row("fit_decay", "Fit falls off by rank", 1, 12, 0.5, (n) => `${n}`)}
      {Row("max_rank", "Candidate buyer down to rank", 1, 24, 1, (n) => `#${n}`)}
      {Row("slots", "Pieces per collector", 1, 5, 1, (n) => `${n}`)}
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
              <line x1={L} x2={w - R} y1={y(t)} y2={y(t)} stroke="var(--line)" />
              <text x={L - 6} y={y(t) + 3} textAnchor="end" fill="var(--muted)" fontSize={10} fontFamily="var(--mono)">{usdK(Math.round(t))}</text>
            </g>
          ))}
          {[50000, 100000, 150000, 200000].map((t) => (
            <text key={t} x={x(t)} y={h - 8} textAnchor="middle" fill="var(--muted)" fontSize={10} fontFamily="var(--mono)">{usdK(t)}</text>
          ))}
          <path d={line} fill="none" stroke="var(--emerald)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          <line x1={x(budget)} x2={x(budget)} y1={T} y2={h - B} stroke="var(--amber)" strokeWidth={1} strokeDasharray="3 3" />
          {nearest && <circle cx={x(nearest.budget)} cy={y(nearest.value)} r={4.5} fill="var(--amber)" stroke="var(--bg)" strokeWidth={2} />}
          {hv && (
            <>
              <line x1={x(hv.budget)} x2={x(hv.budget)} y1={T} y2={h - B} stroke="var(--line-2)" />
              <circle cx={x(hv.budget)} cy={y(hv.value)} r={4} fill="var(--emerald)" stroke="var(--bg)" strokeWidth={2} />
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
  const reason = pick
    ? pick.buyer ? `Placed with ${colBy[pick.buyer]?.name}, who ranks it #${pick.rank} of ${total}.` : "Bought, but no buyer could be placed."
    : eligible.length === 0
      ? `No collector who ranks this within #${maxRank} has the capacity for ${usd(lot.resale)}.`
      : eligible.every((r) => placed.has(r.collector))
        ? `Everyone in range for it (${eligible.slice(0, 3).map((r) => colBy[r.collector]?.name).join(", ")}) already has a piece placed.`
        : "Collectors are in range, but this budget earns more fit-weighted value elsewhere. Force it in to see the cost.";
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" aria-label={lot.name}>
        <div className="dhead"><span className="up muted">Lot {String(lot.lot_no).padStart(2, "0")}</span><button className="btn" onClick={onClose}>Close</button></div>
        <img className="hero" src={lot.image} alt={lot.name} />
        <div className="dsec">
          <h2>{lot.name}</h2>
          <div className="note" style={{ marginTop: 4 }}>{lot.description}</div>
          <div className="kv" style={{ marginTop: 10 }}>
            <div><div className="up muted">Ask</div><div className="big">{usd(lot.ask)}</div></div>
            <div><div className="up muted">Your resale est.</div><div className="big">{usd(lot.resale)}</div></div>
            <div><div className="up muted">Paper margin</div><div className="big">{Math.round(((lot.resale - lot.ask) / lot.ask) * 100)}%</div></div>
          </div>
        </div>
        <div className="dsec">
          <span className="up">Decision</span>
          <div>{reason}</div>
          <div className="row" style={{ marginTop: 8 }}>
            {!pick && <button className="btn primary" disabled={loading} onClick={force}>{loading ? "Solving…" : "Force it in: what does it cost?"}</button>}
          </div>
          {what && (what.feasible ? (
            <div style={{ marginTop: 8 }}>
              <div>Insisting on this lot changes fit-weighted value by <b className={(what.value_delta ?? 0) < 0 ? "red" : "em"}>{signed(what.value_delta ?? 0)}</b> and paper margin by <span className="num">{signed(what.margin_delta ?? 0)}</span>.</div>
              {!!what.displaced?.length && <div className="note">Pushes out: {what.displaced.map((x) => lotBy[x]?.name).join(", ")}.</div>}
              {!!what.added?.length && <div className="note">Brings in: {what.added.map((x) => lotBy[x]?.name).join(", ")}.</div>}
              <div className="note">{what.buyer ? `Would be placed with ${colBy[what.buyer]?.name} at #${what.rank}.` : "No collector could be placed against it."}</div>
            </div>
          ) : <div className="note" style={{ marginTop: 8 }}>{what.reason}</div>)}
        </div>
        <div className="dsec" style={{ padding: 0 }}>
          <span className="up" style={{ padding: "12px 14px 6px" }}>Who ranks it where</span>
          <table>
            <thead><tr><th>Collector</th><th title="Blend of recent behavior and purchases">Book</th><th title="Full behavior sequence">Seq</th><th title="Purchases only">Buys</th><th title="Tag-overlap baseline, not BehaviorGPT">Tags</th><th></th></tr></thead>
            <tbody>
              {rows.slice(0, 10).map((r) => {
                const passed = passes.some(([l, c]) => l === lot.id && c === r.collector);
                return (
                  <tr key={r.collector} className={`${pick?.buyer === r.collector ? "hl" : ""} ${passed ? "dim" : ""}`}>
                    <td className="text">{colBy[r.collector]?.name}{!r.affordable && <span className="muted"> · over capacity</span>}</td>
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
        <div className="dsec note">Stand-in photo: “{lot.credit.title}” by {lot.credit.author || "unknown"}, {lot.credit.license}, via <a href={lot.credit.landing_url} target="_blank" rel="noreferrer">{lot.credit.source}</a>. The lot itself, its ask and resale are invented.</div>
      </aside>
    </>
  );
}

function CollectorDrawer({ c, res, lotBy, signals, onClose, addSearch }: {
  c: Collector; res: Result; lotBy: Record<string, Piece>; signals: Signal[]; onClose: () => void; addSearch: (q: string) => void;
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
        <div className="dhead"><span className="up muted">Collector</span><button className="btn" onClick={onClose}>Close</button></div>
        <div className="dsec">
          <h2>{c.name}</h2>
          <div className="muted">{c.city}</div>
          <div className="note" style={{ marginTop: 4 }}>{c.blurb}</div>
          <div className="kv" style={{ marginTop: 10 }}>
            <div><div className="up muted">Capacity</div><div className="big">{usdK(c.capacity)}</div></div>
            <div><div className="up muted">Past spend</div><div className="big">{usdK(c.lifetime_spend)}</div></div>
            <div><div className="up muted">Purchases</div><div className="big">{c.orders}</div></div>
          </div>
          <div className="note" style={{ marginTop: 6 }}>{c.capacity_note}</div>
        </div>
        <div className="dsec">
          <span className="up">Log a signal from today</span>
          <form className="row" onSubmit={(e) => { e.preventDefault(); submit(q); }}>
            <input className="input" style={{ flex: 1, minWidth: 180 }} value={q} maxLength={120} placeholder="They called asking about…" onChange={(e) => setQ(e.target.value)} />
            <button className="btn primary" type="submit">Re-rank live</button>
          </form>
          <div className="row" style={{ marginTop: 6 }}>
            {["sapphire ring", "gold chain", "art deco", "loose emerald", "tennis bracelet"].map((s) => (
              <button key={s} className="chip n" onClick={() => submit(s)}>{s}</button>
            ))}
          </div>
          {signals.length > 0 && <div className="note" style={{ marginTop: 6 }}>Logged today: {signals.map((s) => (s.q ? `“${s.q}”` : lotBy[s.id!]?.name)).join(", ")}</div>}
        </div>
        {drift && (
          <div className="dsec">
            <span className="up">Recent behavior vs what they buy</span>
            <div className="note" style={{ marginBottom: 6 }}>Average gap of {drift.gap} places across this batch between the two rankings.</div>
            <div className="row" style={{ alignItems: "flex-start" }}>
              <div style={{ flex: 1, minWidth: 180 }}><div className="em" style={{ fontSize: 12 }}>Rising with recent behavior</div>{drift.rising.map((x) => <div key={x} className="note">{lotBy[x]?.name}</div>)}</div>
              <div style={{ flex: 1, minWidth: 180 }}><div className="am" style={{ fontSize: 12 }}>Fading</div>{drift.fading.map((x) => <div key={x} className="note">{lotBy[x]?.name}</div>)}</div>
            </div>
          </div>
        )}
        <div className="dsec">
          <span className="up">Last events BehaviorGPT read ({c.event_count} in all, invented)</span>
          {c.timeline.map((e, i) => (
            <div className="event" key={i}>
              <span className={e.type === "order" ? "em" : "muted"}>{label(e)}</span>
              {e.image ? <img src={e.image} alt="" /> : <span />}
              <span>{e.name ?? `“${e.q}”`}</span>
            </div>
          ))}
        </div>
        <div className="dsec">
          <span className="up">Source for them: next in the wider catalog</span>
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
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" aria-label="Photo credits">
        <div className="dhead"><span className="up muted">Photo credits</span><button className="btn" onClick={onClose}>Close</button></div>
        <div className="dsec note">Photos stand in for fictional lots. Descriptions, asks and resale figures are invented and say nothing about the pictured objects or their owners. The full list for every image is in CREDITS.md in the repository.</div>
        <div className="dsec">
          {lots.map((l) => (
            <div key={l.id} className="note" style={{ marginBottom: 6 }}>
              <b className="ink2">{l.name}</b>: “{l.credit.title}” by {l.credit.author || "unknown"}, <a href={l.credit.license_url} target="_blank" rel="noreferrer">{l.credit.license}</a>, <a href={l.credit.landing_url} target="_blank" rel="noreferrer">{l.credit.source}</a>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}
