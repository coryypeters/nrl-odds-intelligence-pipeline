import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { fetchMatch } from './api.js'
import { Crest } from './App.jsx'
import { teamColours } from './teams.js'

const NZ_TZ = 'Pacific/Auckland'
function koLabel(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d)) return ''
  return d.toLocaleString('en-NZ', { timeZone: NZ_TZ, weekday: 'short', day: 'numeric',
    month: 'short', hour: 'numeric', minute: '2-digit' })
}
function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString('en-NZ', { timeZone: NZ_TZ, hour: '2-digit', minute: '2-digit' })
}

/* Build a plain-language, data-grounded read of the market. */
function marketRead(d) {
  const lines = []
  const fav = d.favourite
  const probs = d.implied?.fair_probabilities || {}
  if (fav && probs[fav] != null) {
    lines.push({
      tone: 'fav',
      title: 'Market favourite',
      body: `${fav} — the market's vig-removed implied chance is ${probs[fav]}%. ` +
            `This reflects where the money sits across ${d.n_books} books, not a form prediction.`,
    })
  }
  // movement read
  const drift = d.drift || {}
  for (const [team, info] of Object.entries(drift)) {
    if (Math.abs(info.change_pct) >= 4) {
      const dir = info.change_pct < 0 ? 'shortened' : 'drifted out'
      lines.push({
        tone: info.change_pct < 0 ? 'short' : 'long',
        title: `${team} has ${dir}`,
        body: `Best price moved ${info.open} → ${info.current} (${info.change_pct > 0 ? '+' : ''}${info.change_pct}%) ` +
              `since we started tracking. ${info.change_pct < 0 ? 'Money has come for this side.' : 'The market has eased off this side.'}`,
      })
    }
  }
  // value
  for (const v of (d.value_flags || [])) {
    lines.push({
      tone: 'value',
      title: `Value flag: ${v.outcome}`,
      body: `${v.bookmaker} is offering ${v.price}, about ${v.edge_pct}% above the ${v.median} consensus. ` +
            `If you were backing ${v.outcome}, ${v.bookmaker} is the standout price right now.`,
    })
  }
  // arb
  if (d.arbitrage?.is_arb) {
    lines.push({
      tone: 'arb',
      title: `Arbitrage window — ${d.arbitrage.profit_pct}% locked`,
      body: `Backing every outcome at the best available price across books returns a guaranteed ` +
            `${d.arbitrage.profit_pct}% regardless of result. These close fast and books may limit stakes.`,
    })
  }
  if (lines.length === 1) {
    lines.push({
      tone: 'flat',
      title: 'Market is settled',
      body: 'No significant line movement, value gaps, or arbitrage in the current data. ' +
            'Prices across books are tightly aligned.',
    })
  }
  return lines
}

/* Honest recommendation derived purely from signal strength in the data. */
function recommendation(d) {
  if (d.arbitrage?.is_arb) {
    return { level: 'Actionable', tone: 'arb',
      text: `Arbitrage available (${d.arbitrage.profit_pct}%). This is a pure-math edge from price ` +
            `differences across books — the strongest signal the data can show.` }
  }
  if ((d.value_flags || []).length) {
    const v = d.value_flags[0]
    return { level: 'Worth a look', tone: 'value',
      text: `${v.outcome} at ${v.bookmaker} (${v.price}) sits ${v.edge_pct}% above consensus. ` +
            `If backing ${v.outcome}, take that price — but this is a market gap, not a form edge.` }
  }
  const fav = d.favourite
  const probs = d.implied?.fair_probabilities || {}
  const drift = d.drift?.[fav]
  if (fav && drift && drift.change_pct < -3) {
    return { level: 'Note the move', tone: 'short',
      text: `${fav} is the favourite (${probs[fav]}%) and has been shortening — money is backing this side. ` +
            `The market agrees, so there's little value left in the price.` }
  }
  return { level: 'No edge', tone: 'flat',
    text: `The market favours ${fav || 'neither side strongly'}${fav ? ` (${probs[fav]}%)` : ''}, ` +
          `but prices are efficient and aligned across books. No data-driven edge to act on.` }
}

export default function MatchDetail() {
  const { eventId } = useParams()
  const navigate = useNavigate()
  const [d, setD] = useState(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () => fetchMatch(eventId).then(x => { if (alive) setD(x) }).catch(() => setErr(true))
    load()
    const id = setInterval(load, 15000)  // refresh analysis every 15s
    return () => { alive = false; clearInterval(id) }
  }, [eventId])

  if (err) return <Shell><div className="empty">Couldn't load this match.</div></Shell>
  if (!d) return <Shell><div className="empty">Loading match analysis…</div></Shell>
  if (!d.found) return <Shell><div className="empty">No data for this match yet. It may have left the live feed.</div></Shell>

  const reads = marketRead(d)
  const rec = recommendation(d)
  const probs = d.implied?.fair_probabilities || {}
  const series = (d.movement_series || []).map(r => ({ ...r, label: fmtTime(r.t) }))
  const colors = ['var(--aqua)', 'var(--purple)', 'var(--lime)']

  return (
    <Shell>
      <button className="back" onClick={() => navigate('/')}>← Back to terminal</button>

      {/* Match header */}
      <div className="md-head glass">
        <div className="md-teams">
          <Crest team={d.home_team} size={44} />
          <div className="md-vs">
            <div className="md-title">{d.home_team} <span className="vs">v</span> {d.away_team}</div>
            <div className="md-meta mono">{koLabel(d.commence_time)} · {d.n_books} books · {d.snapshots_seen} snapshots</div>
          </div>
          <Crest team={d.away_team} size={44} />
        </div>
        {d.score && Object.keys(d.score.scores || {}).length > 0 && (
          <div className="score-strip">
            <span className={`score-state ${d.score.completed ? 'done' : 'live'}`}>
              {d.score.completed ? 'FULL TIME' : '● LIVE'}
            </span>
            {Object.entries(d.score.scores).map(([team, sc]) => (
              <span key={team} className="score-item mono">
                {team} <b>{sc}</b>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Projected margin (derived model) */}
      {d.margin_model && (
        <section className="panel md-margin">
          <div className="panel-head">
            <h2><span className="ic">↔</span> Projected margin <span className="derived-tag">derived model</span></h2>
          </div>
          <div className="margin-body">
            <div className="margin-fig">
              <span className="margin-team">{d.margin_model.favourite}</span>
              <span className="margin-val mono">−{d.margin_model.expected_margin}</span>
              <span className="margin-unit">pts</span>
            </div>
            <div className="margin-read">
              <div className={`margin-band band-${d.margin_model.confidence_band.split(' ')[0].toLowerCase()}`}>
                {d.margin_model.confidence_band}
              </div>
              <p>Modelled expected winning margin for {d.margin_model.favourite}, derived from the
                 market's {d.margin_model.win_prob}% win probability. {d.margin_model.note}</p>
            </div>
          </div>
        </section>
      )}

      {/* Probability split bar */}
      <div className="md-grid">
        <section className="panel">
          <div className="panel-head"><h2><span className="ic">◑</span> Implied probability (vig removed)</h2></div>
          <div className="prob-wrap">
            <div className="prob-bar">
              {d.outcomes.map((o, i) => (
                <div key={o} className="prob-seg" style={{
                  width: `${probs[o] || 0}%`,
                  background: teamColours(o === d.home_team ? d.home_team : (o === d.away_team ? d.away_team : o))[0],
                }} title={`${o}: ${probs[o]}%`} />
              ))}
            </div>
            <div className="prob-legend">
              {d.outcomes.map((o) => (
                <div key={o} className="prob-item">
                  <span className="prob-pct mono">{probs[o] ?? '—'}%</span>
                  <span className="prob-team">{o}</span>
                </div>
              ))}
            </div>
            <div className="margin-note mono">
              Bookmaker margin: {d.implied?.median_overround}% &nbsp;·&nbsp;
              Best-line overround: {d.implied?.best_overround}%
              {d.arbitrage?.is_arb && <span className="arb-chip"> ARB {d.arbitrage.profit_pct}%</span>}
            </div>
          </div>
        </section>

        {/* Recommendation */}
        <section className="panel">
          <div className="panel-head"><h2><span className="ic">◆</span> Data read</h2></div>
          <div className={`rec rec-${rec.tone}`}>
            <div className="rec-level">{rec.level}</div>
            <div className="rec-text">{rec.text}</div>
          </div>
        </section>
      </div>

      {/* Market signals */}
      <section className="panel">
        <div className="panel-head"><h2><span className="ic">⚡</span> Market signals</h2></div>
        <div className="signals">
          {reads.map((r, i) => (
            <div key={i} className={`signal signal-${r.tone}`}>
              <div className="signal-title">{r.title}</div>
              <div className="signal-body">{r.body}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Movement chart */}
      <section className="panel">
        <div className="panel-head"><h2><span className="ic">⟋</span> Line movement</h2></div>
        <div className="chart-wrap">
          {series.length < 2
            ? <div className="empty">Not enough snapshots yet to chart movement — check back as more polls arrive.</div>
            : (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={series} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
                  <XAxis dataKey="label" tick={{ fill: 'var(--faint)', fontSize: 11 }} stroke="var(--border)" />
                  <YAxis domain={['auto', 'auto']} tick={{ fill: 'var(--faint)', fontSize: 11 }} stroke="var(--border)" />
                  <Tooltip contentStyle={{ background: 'var(--glass-2)', border: '1px solid var(--border-hi)', borderRadius: 10, fontSize: 12, backdropFilter: 'blur(10px)' }}
                           labelStyle={{ color: 'var(--muted)' }} />
                  {d.outcomes.map((o, i) => (
                    <Line key={o} type="monotone" dataKey={o} stroke={colors[i % colors.length]}
                          strokeWidth={2.5} dot={false} isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            )}
        </div>
      </section>

      {/* Full book-by-book table */}
      <section className="panel">
        <div className="panel-head"><h2><span className="ic">▤</span> All books</h2></div>
        <div className="book-grid">
          {d.outcomes.map((o) => (
            <div key={o} className="book-col">
              <div className="book-col-head">{o}</div>
              {(d.book_table[o] || []).map((row, i) => (
                <div key={row.bookmaker} className={`book-row ${i === 0 ? 'best' : ''}`}>
                  <span className="book-name">{row.bookmaker}</span>
                  <span className="book-price mono">{row.price.toFixed(2)}</span>
                  {i === 0 && <span className="book-best-tag">BEST</span>}
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>

      <div className="rg-strip" style={{ margin: '18px 0 0' }}>
        <span className="shield">⛉</span>
        <span>Analysis is derived from odds data only — no team form, injuries, or predictive model.
          Treat it as market intelligence, not a tip. Bet within your limits ·
          <a href="https://www.choicenotchance.org.nz/" target="_blank" rel="noopener noreferrer"> Choice Not Chance</a> · 0800 654 655.</span>
      </div>
    </Shell>
  )
}

function Shell({ children }) {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <span className="brand-name">Odds<b>Intelligence</b></span>
          <span className="brand-sub">match analysis</span>
        </div>
      </header>
      <main className="md-main">{children}</main>
    </div>
  )
}
