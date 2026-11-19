export const meta = {
  name: 'readings',
  description: 'Work each distinct reading of an unclear message in an agent of its own, then compare what they came to',
  whenToUse: 'A message leaves two or more distinct readings open, and one start would have to guess between them',
  phases: [{ title: 'Readings', detail: 'one agent for each reading, a reading that writes files in a git worktree of its own' }],
}

// args: {"words": "<the message>", "readings": ["<a reading>", {"text": "<a reading>", "writes": true}, ...]}
//
// A reading given as a string, or without `writes: true`, changes no file and shares the session's checkout. A
// reading with `writes: true` runs in a git worktree of its own and commits there. The run returns one of:
//   {state: "collapsed", result, readings, lost, next}             the readings came to one result
//   {state: "forked", question, default, options, lost, next}      they differ, or one stopped on a question for ezexe
//   {state: "lost", lost, next}                                    no reading gave a result
// A run takes no input from a person and a subagent has no AskUserQuestion, by workflows.md, "Behavior and limits",
// and sub-agents.md, "Available tools". So a reading that cannot go on without ezexe returns its question as data,
// and the session puts one question to ezexe after the run.

const MOST = 4 // the options one AskUserQuestion takes, so the readings one run works

// The words that carry no content, as scripts/plans.py COMMON and scripts/puppeteer.py STOP hold them:
// tests/p4-phi/test_readings.py holds the two lists here to those two.
const COMMON = `the and for with from that this into onto then than when what which each step steps plan run
make add fix test tests check update write read build its their them they any all are was were has have had not
but use used using new old one two first next last`
const STOP = `phi session sessions p4 plugin plugins please make sure also just now then when with that this
there their them they have has should would could will want need like into from about your you our out get got use
using one two all any each every not and for the are was were been being its it's can may must more most some such
than too very what which who how why where while after before over under again new old`
const DROPPED = new Set(`${COMMON} ${STOP}`.split(/\s+/).filter(Boolean))

const oneLine = t => String(t == null ? '' : t).split(/\s+/).filter(Boolean).join(' ')
const cut = (t, n) => {
  const s = oneLine(t)
  return s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s
}
const contentWords = t =>
  new Set(
    (String(t == null ? '' : t).match(/[A-Za-z_][A-Za-z0-9_]{2,}/g) || [])
      .map(w => w.toLowerCase())
      .filter(w => !DROPPED.has(w)),
  )
const plain = t => oneLine(t).toLowerCase().replace(/^[ .]+|[ .]+$/g, '')

// Two results are one result when they read the same with case, spacing and a closing full stop dropped, or when
// they share two or more content words that make up four fifths of the shorter one's, with no more than two
// content words between their counts.
function sameResult(a, b) {
  if (plain(a) === plain(b)) return true
  const wa = contentWords(a)
  const wb = contentWords(b)
  const both = [...wa].filter(w => wb.has(w)).length
  const part = wa.size && wb.size ? both / Math.min(wa.size, wb.size) : 0
  return both >= 2 && part >= 0.8 && Math.abs(wa.size - wb.size) <= 2
}

const USAGE =
  'readings takes args {"words": "<the message>", "readings": [...]} with two or more distinct readings, ' +
  'each a string or {"text": "<the reading>", "writes": true}'

let given = args
if (typeof given === 'string') {
  try {
    given = JSON.parse(given)
  } catch (e) {
    throw new Error(USAGE)
  }
}
if (Array.isArray(given)) given = { readings: given }
if (!given || typeof given !== 'object') throw new Error(USAGE)

const words = oneLine(given.words)
const seen = new Set()
const distinct = []
for (const r of Array.isArray(given.readings) ? given.readings : []) {
  const named = r && typeof r === 'object'
  const text = oneLine(named ? r.text : r)
  if (!text || seen.has(text.toLowerCase())) continue
  seen.add(text.toLowerCase())
  distinct.push({ text, writes: Boolean(named && r.writes === true) })
}
if (distinct.length < 2) throw new Error(USAGE)

const readings = distinct.slice(0, MOST).map((r, i) => ({ k: i + 1, text: r.text, writes: r.writes }))
const dropped = distinct.slice(MOST).map(r => r.text)
if (dropped.length) {
  log(
    `readings: ${dropped.length} reading${dropped.length === 1 ? '' : 's'} past the first ${MOST} left out, ` +
      `since one question to ezexe takes ${MOST} options`,
  )
}

const RESULT = {
  type: 'object',
  required: ['result', 'question'],
  properties: {
    result: {
      type: 'string',
      description: 'What this reading comes to, as one plain sentence that states the outcome itself',
    },
    question: {
      type: 'string',
      description: 'Empty, unless the reading cannot go on without ezexe: then the one question only ezexe can answer',
    },
    wrote: {
      type: 'array',
      items: { type: 'string' },
      description: 'Each file this reading changed, as a path from the repository root, and empty when it changed none',
    },
    branch: {
      type: 'string',
      description: 'The branch the changed files are committed on, and empty when no file changed',
    },
    worktree: {
      type: 'string',
      description: 'The folder of the git worktree this reading ran in, and empty when it shared the checkout',
    },
  },
}

const WRITES =
  'You run in a git worktree of your own, on a branch of your own. Change files only there, and commit what you ' +
  'change on that branch, so the session finds the work by the branch. Push nothing and merge nothing. Return the ' +
  'branch `git rev-parse --abbrev-ref HEAD` prints as `branch`, the folder `git rev-parse --show-toplevel` prints ' +
  'as `worktree`, and each file you changed, as a path from the repository root, in `wrote`.'
const READS =
  'This reading changes no file. You share the checkout with the session and with the other readings, so write no ' +
  'file there and commit nothing. Leave `branch`, `worktree` and `wrote` empty.'
const DECIDE =
  'A question that the code, the history, the issues or the current outside documentation can answer is yours to ' +
  'research and decide. A question only ezexe can answer ends the reading: stop there, put that one question in ' +
  '`question`, and say in `result` how far the reading got. You cannot ask ezexe yourself: the session asks once, ' +
  'after every reading has returned. Leave `question` empty when the reading went through.'
const STATE =
  'Return `result` as one plain sentence that states what this reading comes to: the outcome itself, and no ' +
  'account of your steps. It is compared word for word with the results of the other readings, and readings that ' +
  'state one outcome collapse into it.'

function brief(r, n) {
  return [
    `This is reading ${r.k} of ${n} of one message that leaves more than one reading open. Each reading is worked ` +
      'by an agent of its own, blind to the others, and their results are then compared.',
    '',
    ...(words ? [`The message: ${words}`, ''] : []),
    `Your reading of it: ${r.text}`,
    '',
    'Work only this reading, through to what it comes to.',
    '',
    r.writes ? WRITES : READS,
    '',
    DECIDE,
    '',
    STATE,
  ].join('\n')
}

phase('Readings')
const n = readings.length
// A barrier, since the compare needs every reading's result at once.
const got = await parallel(
  readings.map(r => async () => {
    try {
      const out = await agent(brief(r, n), {
        label: `reading ${r.k}`,
        phase: 'Readings',
        schema: RESULT,
        ...(r.writes ? { isolation: 'worktree' } : {}),
      })
      return { out, why: out ? '' : 'its agent was stopped or failed' }
    } catch (e) {
      return { out: null, why: oneLine(e && e.message ? e.message : e) || 'its agent failed' }
    }
  }),
)

const entries = readings.map((r, i) => {
  const g = got[i] || { out: null, why: 'its agent failed' }
  const out = g.out && typeof g.out === 'object' ? g.out : null
  const result = oneLine(out && out.result)
  const question = oneLine(out && out.question)
  if (!result && !question) return { k: r.k, text: r.text, why: g.why || 'it returned no result' }
  const entry = { k: r.k, text: r.text, result, question }
  const wrote = (out && Array.isArray(out.wrote) ? out.wrote : []).map(oneLine).filter(Boolean)
  // Only a reading that ran in a worktree of its own and changed a file has a branch to find: a worktree left
  // unchanged is removed with its branch, and a reading that shared the checkout is on the session's own branch.
  if (r.writes && wrote.length) {
    entry.wrote = wrote
    entry.branch = oneLine(out.branch)
    entry.worktree = oneLine(out.worktree)
  }
  return entry
})

const lost = entries.filter(e => e.why)
const live = entries.filter(e => !e.why)
const through = live.filter(e => !e.question)
const asking = live.filter(e => e.question)
const base = { words, ...(dropped.length ? { dropped } : {}) }
const gone = !lost.length
  ? ''
  : lost.length === 1
    ? ` Reading ${lost[0].k} gave no result.`
    : ` Readings ${lost.map(e => e.k).join(', ')} gave no result.`

if (!live.length) {
  return {
    state: 'lost',
    ...base,
    lost,
    next: 'No reading gave a result. Run the readings again if the answer is still wanted.',
  }
}

if (!asking.length && through.every(e => sameResult(through[0].result, e.result))) {
  const held = through.find(e => e.branch)
  return {
    state: 'collapsed',
    ...base,
    result: through[0].result,
    readings: through,
    lost,
    next:
      (through.length === 1
        ? `Reading ${through[0].k} alone gave a result: carry it on as the answer, and put no question to ezexe.`
        : 'The readings came to one result: carry it on as the answer, and put no question to ezexe.') +
      gone +
      (held
        ? ` Reading ${held.k} committed its files on the branch \`${held.branch}\`: merge that branch into this ` +
          "session's branch."
        : ''),
  }
}

const first = (through[0] || asking[0]).k
return {
  state: 'forked',
  ...base,
  question: words ? `Which reading of "${cut(words, 160)}" is meant?` : 'Which reading is meant?',
  default: first,
  options: live,
  lost,
  next:
    'The readings fork. Put the one `question` to ezexe with `AskUserQuestion`, an option for each entry of ' +
    `\`options\`, reading ${first} first as the recommended one, each option saying what its reading came to or the ` +
    'question it stopped on. Then start the chosen reading as a child session of its own, cut from its `branch` ' +
    'where it has one.' +
    gone,
}
