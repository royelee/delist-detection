export const meta = {
  name: 'diagnosis-truth-normalize',
  description: 'Turn diagnosis reports into truth rows (truth-rules.md), a batch of cases per agent, at most 5 agents at a time',
  phases: [
    { title: 'Normalize', detail: 'one agent per batch: read each report, write its truth row JSON' },
    { title: 'Check', detail: 'every case has a row (code, no agent)' },
  ],
}

const FIELD = { type: 'string' }
const ROW = {
  type: 'object',
  properties: {
    case_id: FIELD, sec_id: FIELD, shape: { type: 'string', enum: ['ending', 'no_ending', 'ending_moved'] },
    fields: { type: 'object', properties: Object.fromEntries(['exit_kind', 'drop_reason', 'continuation',
      'successor_sec_id', 'last_trade_date', 'value_rule', 'cash_per_share', 'cash_currency', 'stock_ratio',
      'price_sec_id', 'price_ticker', 'price_date', 'recovery_ratio'].map(f => [f, FIELD])),
      required: ['exit_kind', 'drop_reason', 'continuation', 'successor_sec_id', 'last_trade_date', 'value_rule',
        'cash_per_share', 'cash_currency', 'stock_ratio', 'price_sec_id', 'price_ticker', 'price_date',
        'recovery_ratio'] },
    internal_last_trade_date: FIELD,
    legs: { type: 'array', items: { type: 'object', properties: { leg: { type: 'integer' }, ratio: FIELD,
      price_sec_id: FIELD, price_ticker: FIELD, price_date: FIELD }, required: ['leg', 'ratio'] } },
    identity_check: { type: ['object', 'null'], properties: { old_cusip: FIELD, new_cusip: FIELD } },
    residual: FIELD,
    pending: { type: 'array', items: { type: 'object', properties: { field: FIELD, question: FIELD },
      required: ['field', 'question'] } },
    notes: FIELD,
  },
  required: ['case_id', 'sec_id', 'shape', 'fields', 'internal_last_trade_date', 'legs', 'identity_check',
    'residual', 'pending', 'notes'],
}
const BATCH = { type: 'object', properties: { rows: { type: 'array', items: ROW } }, required: ['rows'] }

const LIMIT = 5
let running = 0
const waiting = []
async function limited(fn) {
  while (running >= LIMIT) await new Promise(resolve => waiting.push(resolve))
  running++
  try { return await fn() } finally { running--; const next = waiting.shift(); if (next) next() }
}

function prompt(ids) {
  return `Turn ${ids.length} diagnosis report(s) of the delist_detection library into truth rows.

Read first, in the repo (your working directory): .claude/skills/diagnose-delisting/truth-rules.md (your
instructions; follow them exactly) and .claude/skills/diagnose-delisting/reference.md (the contract's fields and
the spec's decisions).

Cases: ${ids.join(', ')}.
For each case: read output/diagnose_unknown_report/reports/<case_id>.md (all sections, including 9) and
output/diagnose_unknown_report/records/<case_id>.json. To look up a sec_id, grep output/securities.csv and
output/ticker_history.csv. Do not fetch from SEC or the web: the report is the evidence.

Write one file per case with the Write tool, BEFORE you return:
output/diagnose_unknown_report/truth_rows/<case_id>.json. Then return {"rows": [...]} with the same objects.
Do not edit any other file, run the pipeline, commit or dispatch subagents.`
}

if (!Array.isArray(args.cases) || !args.cases.length) throw new Error('diagnosis-truth-normalize: args.cases must be a non-empty array of case ids')
const ids = args.cases
const size = args.batch || 10
const batches = []
for (let i = 0; i < ids.length; i += size) batches.push(ids.slice(i, i + size))
log(`${ids.length} cases in ${batches.length} batches, at most ${LIMIT} agents at a time`)

phase('Normalize')
const results = await parallel(batches.map((b, i) => () => limited(() =>
  agent(prompt(b), { label: `normalize:${i + 1}/${batches.length}`, phase: 'Normalize', schema: BATCH,
    model: 'sonnet' }))))

phase('Check')
const got = new Set(results.filter(Boolean).flatMap(r => r.rows.map(x => x.case_id)))
const missing = ids.filter(id => !got.has(id))
const pending = results.filter(Boolean).flatMap(r => r.rows.filter(x => x.pending.length).map(x => x.case_id))
log(`${got.size}/${ids.length} rows; ${missing.length} missing; ${pending.length} with pending fields`)
return { missing, pending }
