/**
 * Team identity system.
 *
 * We can't use trademarked club logos in a public portfolio repo, so each team
 * gets a generated crest from its real club colours + a monogram. This is
 * deterministic (same team -> same crest every time), needs no network, and
 * updates automatically for any team in the feed.
 *
 * TEAM_COLOURS holds primary/secondary for clubs across the covered leagues.
 * Anything not listed falls back to a hashed colour pair so even unknown teams
 * still get a stable, distinct crest.
 */

export const TEAM_COLOURS = {
  // ── NRL ──────────────────────────────────────────────
  'Brisbane Broncos':            ['#6f0f3c', '#fdb913'],
  'Canberra Raiders':            ['#9bca3c', '#1a3a1a'],
  'Canterbury Bulldogs':         ['#005baa', '#ffffff'],
  'Canterbury-Bankstown Bulldogs':['#005baa', '#ffffff'],
  'Cronulla Sharks':             ['#00a9b6', '#231f20'],
  'Cronulla Sutherland Sharks':  ['#00a9b6', '#231f20'],
  'Dolphins':                    ['#d8232a', '#ffd200'],
  'Gold Coast Titans':           ['#009edb', '#d4af37'],
  'Manly Sea Eagles':            ['#6e1f3c', '#ffffff'],
  'Manly Warringah Sea Eagles':  ['#6e1f3c', '#ffffff'],
  'Melbourne Storm':             ['#4b2e83', '#ffd200'],
  'Newcastle Knights':           ['#003faa', '#e2231a'],
  'New Zealand Warriors':        ['#00529b', '#6cc24a'],
  'North Queensland Cowboys':    ['#002b5c', '#ffd200'],
  'Parramatta Eels':             ['#006eb5', '#ffd200'],
  'Penrith Panthers':            ['#231f20', '#009b48'],
  'South Sydney Rabbitohs':      ['#005a30', '#e2231a'],
  'St George Illawarra Dragons': ['#e2231a', '#ffffff'],
  'Sydney Roosters':             ['#0a1f44', '#e2231a'],
  'Wests Tigers':                ['#f68b1f', '#231f20'],
  // ── State of Origin ─────────────────────────────────
  'New South Wales Blues':       ['#0a3d91', '#7ec8e3'],
  'Queensland Maroons':          ['#6b002b', '#ffffff'],
  // ── Six Nations ─────────────────────────────────────
  'England':                     ['#ffffff', '#0a1f44'],
  'France':                      ['#0055a4', '#ef4135'],
  'Ireland':                     ['#169b62', '#ffffff'],
  'Italy':                       ['#0066cc', '#ffffff'],
  'Scotland':                    ['#0a1f44', '#6e3b8e'],
  'Wales':                       ['#c8102e', '#00843d'],
  // ── EPL / UCL (common clubs; extend as needed) ──────
  'Arsenal':                     ['#ef0107', '#ffffff'],
  'Aston Villa':                 ['#670e36', '#95bfe5'],
  'Chelsea':                     ['#034694', '#ffffff'],
  'Liverpool':                   ['#c8102e', '#00b2a9'],
  'Manchester City':             ['#6cabdd', '#1c2c5b'],
  'Manchester United':           ['#da291c', '#ffe500'],
  'Newcastle United':            ['#241f20', '#ffffff'],
  'Tottenham Hotspur':           ['#132257', '#ffffff'],
}

/** Stable fallback colour pair from a team name (so unknowns are consistent). */
function hashColours(name) {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  const hue = h % 360
  const hue2 = (hue + 150) % 360
  return [`hsl(${hue} 55% 42%)`, `hsl(${hue2} 70% 60%)`]
}

/** Monogram: a clean 1–2 letter mark from the team's nickname. */
export function monogram(name) {
  const stop = new Set(['the', 'of', 'and', 'new', 'north', 'south', 'east', 'west',
                        'gold', 'st', 'gold coast'])
  const words = name.split(/\s+/)
  // The nickname is almost always the last word (Warriors, Storm, Blues, Broncos).
  const nick = words[words.length - 1] || name
  // Two letters reads better than one for most nicknames.
  return nick.slice(0, 2).toUpperCase()
}

export function teamColours(name) {
  return TEAM_COLOURS[name] || hashColours(name)
}
