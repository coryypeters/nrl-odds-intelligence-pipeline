import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { fetchEvents, fetchOdds, useEventStream } from './api.js'
import { teamColours, monogram } from './teams.js'

/* Generated team crest: real club colours + monogram, no trademarked logos. */
export function Crest({ team, size = 30 }) {
  const [c1, c2] = teamColours(team)
  return (
    <span
      className="crest"
      title={team}
      style={{
        width: size, height: size, fontSize: size * 0.34,
        background: `linear-gradient(135deg, ${c1} 0%, ${c1} 55%, ${c2} 56%, ${c2} 100%)`,
      }}
    >
      <span className="crest-mono" style={{ color: pickInk(c1) }}>{monogram(team)}</span>
    </span>
  )
}

/* Choose black/white ink for contrast against the crest's primary colour. */
function pickInk(color) {
  // hsl() fallbacks are mid-tone -> white reads fine; for hex, compute luminance.
  if (!color.startsWith('#')) return '#fff'
  const r = parseInt(color.slice(1, 3), 16)
  const g = parseInt(color.slice(3, 5), 16)
  const b = parseInt(color.slice(5, 7), 16)
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return lum > 0.6 ? '#0a1426' : '#ffffff'
}

const KIND_META = {
  movement:  { label: 'Movement', color: 'var(--aqua)' },    // blue = live info
  steam:     { label: 'Steam',    color: 'var(--lime)' },    // green = positive signal
  arbitrage: { label: 'Arb',      color: 'var(--amber)' },   // gold = premium / the prize
}

function timeAgo(ts) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${Math.floor(s / 3600)}h`
}

function dirArrow(direction) {
  if (direction === 'shortened') return '▼'   // price down = money in
  if (direction === 'lengthened') return '▲'  // price up = drifting
  return '·'
}
function dirColor(direction) {
  if (direction === 'shortened') return 'var(--lime)'
  if (direction === 'lengthened') return 'var(--rose)'
  return 'var(--muted)'
}

/* ── Live signal feed: the signature element ──────────────────────────────── */
function FeedRow({ ev, isNew }) {
  const meta = KIND_META[ev.kind] || { label: ev.kind, color: 'var(--muted)' }
  return (
    <div className={`feed-row ${isNew ? 'flash' : ''}`}>
      <div className="feed-tag" style={{ color: meta.color, borderColor: meta.color }}>
        {meta.label}
      </div>
      <div className="crest-pair">
        <Crest team={ev.home_team} size={26} />
        <Crest team={ev.away_team} size={26} />
      </div>
      <div className="feed-body">
        <div className="feed-match">{ev.home_team} <span className="vs">v</span> {ev.away_team}</div>
        <div className="feed-detail mono">{describe(ev)}</div>
      </div>
      <div className="feed-time mono">{timeAgo(ev.detected_at)}</div>
    </div>
  )
}

function describe(ev) {
  if (ev.kind === 'arbitrage') {
    const legs = (ev.legs || []).map(l => `${l.outcome} @${l.price} ${l.bookmaker}`).join('  +  ')
    return `${ev.profit_pct >= 0 ? '+' : ''}${ev.profit_pct}% — ${legs}`
  }
  if (ev.kind === 'steam') {
    return `${ev.outcome} ${dirArrow(ev.direction)} ${ev.avg_pct_change}% · ${ev.n_books ?? (ev.books_moved||[]).length} books`
  }
  // movement
  return `${ev.outcome} @ ${ev.bookmaker}  ${ev.old_price}→${ev.new_price} (${ev.pct_change >= 0 ? '+' : ''}${ev.pct_change}%)`
}

/* Kickoff in NZ local time, with a friendly day label and a live/soon flag.
   commence_time is UTC ISO from The Odds API; Pacific/Auckland handles DST. */
const NZ_TZ = 'Pacific/Auckland'
function kickoff(iso) {
  if (!iso) return { label: '', state: 'unknown' }
  const ko = new Date(iso)
  if (isNaN(ko)) return { label: '', state: 'unknown' }
  const now = new Date()
  const mins = (ko - now) / 60000

  const time = ko.toLocaleTimeString('en-NZ', { timeZone: NZ_TZ, hour: 'numeric', minute: '2-digit' })

  // Day bucket using NZ-local date strings.
  const dayOf = (d) => d.toLocaleDateString('en-NZ', { timeZone: NZ_TZ })
  const today = dayOf(now)
  const tmrw = dayOf(new Date(now.getTime() + 86400000))
  const koDay = dayOf(ko)
  let day
  if (koDay === today) day = 'Today'
  else if (koDay === tmrw) day = 'Tomorrow'
  else day = ko.toLocaleDateString('en-NZ', { timeZone: NZ_TZ, weekday: 'short', day: 'numeric', month: 'short' })

  let state = 'upcoming'
  if (mins <= -1) state = 'live'           // started
  else if (mins <= 60) state = 'soon'      // within the hour
  return { label: `${day} ${time}`, state }
}

/* ── Odds comparison table ────────────────────────────────────────────────── */
function OddsTable({ odds, onPick, picked }) {
  const navigate = useNavigate()
  if (!odds.length) {
    return <div className="empty">No live markets. The poller speeds up as kickoff nears.</div>
  }
  return (
    <div className="odds-list">
      {odds.map((e) => {
        const outcomes = Object.entries(e.best)
        const ko = kickoff(e.commence_time)
        return (
          <div
            key={e.event_id}
            className={`odds-card ${picked === e.event_id ? 'picked' : ''}`}
            onClick={() => navigate(`/match/${e.event_id}`)}
            role="button"
            tabIndex={0}
            onKeyDown={(ev) => { if (ev.key === 'Enter') navigate(`/match/${e.event_id}`) }}
          >
            <div className="odds-match">
              <Crest team={e.home_team} size={22} />
              <Crest team={e.away_team} size={22} />
              <span className="odds-match-text">{e.home_team} <span className="vs">v</span> {e.away_team}</span>
              {ko.label && (
                <span className={`ko ko-${ko.state} mono`}>
                  {ko.state === 'live' ? '● LIVE' : ko.label}
                </span>
              )}
            </div>
            <div className="odds-prices">
              {outcomes.map(([name, info]) => (
                <div className="price-cell" key={name}>
                  <span className="price-team">{name}</span>
                  <span className="price-val mono">{info.price.toFixed(2)}</span>
                  <span className="price-book">{info.bookmaker}</span>
                </div>
              ))}
            </div>
            <div className="odds-actions">
              <button
                className="mini-btn"
                onClick={(ev) => { ev.stopPropagation(); onPick(e.event_id) }}
              >
                Chart movement
              </button>
              <span className="detail-hint">View analysis →</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ── Movement chart: best price drift for the picked event ────────────────── */
function MovementChart({ history, eventName }) {
  if (!history.length) {
    return <div className="empty">Pick a match to chart its line movement as new snapshots arrive.</div>
  }
  const outcomes = Object.keys(history[0]).filter(k => k !== 't')
  const colors = ['var(--aqua)', 'var(--purple)', 'var(--lime)']
  return (
    <div className="chart-wrap">
      <div className="chart-title">{eventName}</div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={history} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
          <XAxis dataKey="t" tick={{ fill: 'var(--faint)', fontSize: 11 }} stroke="var(--border)" />
          <YAxis domain={['auto', 'auto']} tick={{ fill: 'var(--faint)', fontSize: 11 }} stroke="var(--border)" />
          <Tooltip
            contentStyle={{ background: 'var(--glass-2)', border: '1px solid var(--border-hi)', borderRadius: 10, fontSize: 12, backdropFilter: 'blur(10px)' }}
            labelStyle={{ color: 'var(--muted)' }}
          />
          {outcomes.map((o, i) => (
            <Line key={o} type="monotone" dataKey={o} stroke={colors[i % colors.length]}
                  strokeWidth={2.5} dot={false} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/* Market overview: live pipeline stats derived from current data. */
function MarketStats({ events, odds }) {
  const stats = useMemo(() => {
    const arbs = events.filter(e => e.kind === 'arbitrage')
    const steams = events.filter(e => e.kind === 'steam')
    const moves = events.filter(e => e.kind === 'movement')

    // biggest single move in the feed
    let biggest = null
    for (const m of moves) {
      if (!biggest || Math.abs(m.pct_change) > Math.abs(biggest.pct_change)) biggest = m
    }
    // books seen across the odds table
    const books = new Set()
    for (const e of odds) {
      for (const o of Object.values(e.best || {})) if (o.bookmaker) books.add(o.bookmaker)
    }
    // best arb on the board right now
    let topArb = null
    for (const a of arbs) {
      if (!topArb || (a.profit_pct || 0) > (topArb.profit_pct || 0)) topArb = a
    }
    return {
      markets: odds.length,
      signals: events.length,
      arbs: arbs.length,
      steams: steams.length,
      books: books.size,
      biggest,
      topArb,
    }
  }, [events, odds])

  return (
    <section className="panel stats-panel">
      <div className="panel-head"><h2><span className="ic">▦</span> Market overview</h2></div>
      <div className="stats-grid">
        <Stat label="Markets live" value={stats.markets} />
        <Stat label="Signals today" value={stats.signals} />
        <Stat label="Arbs found" value={stats.arbs} accent={stats.arbs ? 'amber' : null} />
        <Stat label="Steam moves" value={stats.steams} accent={stats.steams ? 'lime' : null} />
        <Stat label="Books tracked" value={stats.books} />
        <Stat label="Leagues" value="NRL" small />
      </div>
      {stats.biggest && (
        <div className="stats-highlight">
          <span className="sh-label">Biggest move</span>
          <span className="sh-body mono">
            {stats.biggest.outcome} {dirArrow(stats.biggest.direction)} {Math.abs(stats.biggest.pct_change)}%
            <span className="sh-sub"> · {stats.biggest.home_team} v {stats.biggest.away_team}</span>
          </span>
        </div>
      )}
      {stats.topArb && (
        <div className="stats-highlight arb">
          <span className="sh-label">Best arb</span>
          <span className="sh-body mono">
            +{stats.topArb.profit_pct}%
            <span className="sh-sub"> · {stats.topArb.home_team} v {stats.topArb.away_team}</span>
          </span>
        </div>
      )}
    </section>
  )
}

function Stat({ label, value, accent, small }) {
  return (
    <div className="stat">
      <div className={`stat-val mono ${accent ? `accent-${accent}` : ''} ${small ? 'small' : ''}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

export default function App() {
  const [events, setEvents] = useState([])
  const [odds, setOdds] = useState([])
  const [filter, setFilter] = useState('all')
  const [picked, setPicked] = useState(null)
  const [history, setHistory] = useState([])
  const [newKeys, setNewKeys] = useState(new Set())
  const { status, last } = useEventStream()

  // initial load + periodic odds refresh
  useEffect(() => {
    fetchEvents().then(setEvents).catch(() => {})
    fetchOdds().then(setOdds).catch(() => {})
    const id = setInterval(() => fetchOdds().then(setOdds).catch(() => {}), 30000)
    return () => clearInterval(id)
  }, [])

  // prepend live events as they arrive
  useEffect(() => {
    if (!last) return
    setEvents((prev) => {
      if (prev.some(e => e.event_key === last.event_key)) return prev
      return [last, ...prev].slice(0, 200)
    })
    setNewKeys((s) => new Set(s).add(last.event_key))
  }, [last])

  // build the movement-chart series for the picked event from its odds history
  useEffect(() => {
    if (!picked) { setHistory([]); return }
    const ev = odds.find(o => o.event_id === picked)
    if (!ev) return
    const point = { t: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }
    for (const [name, info] of Object.entries(ev.best)) point[name] = info.price
    setHistory((h) => [...h.slice(-29), point])  // keep last 30 points
  }, [picked, odds])

  // Collapse noise: repeated movement events for the same outcome+book keep only
  // the most recent. Steam and arbitrage are always shown in full (rare signals).
  const collapsed = useMemo(() => {
    const seenMove = new Set()
    const out = []
    for (const e of events) {  // events are newest-first
      if (e.kind === 'movement') {
        const k = `${e.event_id}|${e.outcome}|${e.bookmaker}`
        if (seenMove.has(k)) continue   // drop older duplicate move
        seenMove.add(k)
      }
      out.push(e)
    }
    return out
  }, [events])

  const filtered = useMemo(
    () => filter === 'all' ? collapsed : collapsed.filter(e => e.kind === filter),
    [collapsed, filter]
  )
  const pickedName = useMemo(() => {
    const e = odds.find(o => o.event_id === picked)
    return e ? `${e.home_team} v ${e.away_team}` : ''
  }, [odds, picked])

  const counts = useMemo(() => {
    const c = { all: events.length, movement: 0, steam: 0, arbitrage: 0 }
    for (const e of events) c[e.kind] = (c[e.kind] || 0) + 1
    return c
  }, [events])

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <span className="brand-name">Odds<b>Intelligence</b></span>
          <span className="brand-sub">live terminal</span>
        </div>
        <div className={`status status-${status}`}>
          <span className={`dot ${status === 'live' ? 'pulse' : ''}`} />
          {status === 'live' ? 'LIVE' : status === 'reconnecting' ? 'RECONNECTING' : 'CONNECTING'}
        </div>
      </header>

      {/* HERO */}
      <section className="hero">
        <div className="hero-bg" style={{
          backgroundColor: '#0a1426',
          backgroundImage:
            'linear-gradient(115deg, rgba(34,211,238,0.10), rgba(139,92,246,0.10)),' +
            'url("https://images.unsplash.com/photo-1459865264687-595d652de67e?auto=format&fit=crop&w=1600&q=70")',
          backgroundSize: 'cover',
          backgroundPosition: 'center 35%',
        }} />
        <div className="hero-veil" />
        <div className="hero-inner">
          <span className="hero-eyebrow">● Live market intelligence</span>
          <h1>Bet smarter on <b>live sport</b></h1>
          <p>Compare odds across books, track real-time line movement and steam,
             surface arbitrage windows the moment they open — and manage your play responsibly.</p>
          <div className="hero-cta">
            <button className="btn btn-primary"
                    onClick={() => document.getElementById('markets')?.scrollIntoView({ behavior: 'smooth' })}>
              View live odds
            </button>
            <a className="btn btn-glass"
               href="https://www.choicenotchance.org.nz/" target="_blank" rel="noopener noreferrer">
              ⛉ Set betting limits
            </a>
          </div>
        </div>
      </section>

      {/* Responsible-gambling strip */}
      <div className="rg-strip">
        <span className="shield">⛉</span>
        <span>
          This is an odds-analysis tool, not a bookmaker. Bet within your limits.
          Free, confidential support in NZ: <a href="https://www.choicenotchance.org.nz/" target="_blank" rel="noopener noreferrer">Choice Not Chance</a> · 0800 654 655.
        </span>
      </div>

      <main className="grid" id="markets">
        {/* LEFT — sticky: live signal feed + market overview */}
        <div className="left-col">
          <section className="panel feed-panel">
            <div className="panel-head">
              <h2><span className="ic">⚡</span> Signal feed</h2>
              <div className="filters">
                {['all', 'movement', 'steam', 'arbitrage'].map(k => (
                  <button key={k}
                          className={`chip ${filter === k ? 'on' : ''}`}
                          onClick={() => setFilter(k)}>
                    {k === 'all' ? 'All' : KIND_META[k].label}
                    <span className="chip-n">{counts[k] ?? 0}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="feed-scroll">
              {filtered.length === 0
                ? <div className="empty">Waiting for signals. Movement, steam and arbs surface here the moment they're detected.</div>
                : filtered.map((ev) => (
                    <FeedRow key={ev.event_key + ev.detected_at} ev={ev} isNew={newKeys.has(ev.event_key)} />
                  ))}
            </div>
          </section>

          <MarketStats events={events} odds={odds} />
        </div>

        {/* RIGHT — odds table + chart stacked */}
        <div className="right-col">
          <section className="panel">
            <div className="panel-head"><h2><span className="ic">◷</span> Best odds by market</h2></div>
            <OddsTable odds={odds} onPick={setPicked} picked={picked} />
          </section>

          <section className="panel">
            <div className="panel-head"><h2><span className="ic">⟋</span> Line movement</h2></div>
            <MovementChart history={history} eventName={pickedName} />
          </section>
        </div>
      </main>

      <footer className="foot">
        <b>Odds Intelligence</b> — a real-time odds analytics pipeline (The Odds API → Redis Streams → detection → WebSocket).
        Built for portfolio demonstration. Odds shown are aggregated for analysis and may lag bookmaker prices.
        Gamble responsibly · 18+.
      </footer>
    </div>
  )
}
