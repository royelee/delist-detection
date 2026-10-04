export const meta = {
  name: 'diagnosis-truth-loop',
  description: 'The diagnosis truth loop of one sub-plan: list new errors, diagnose and verify each, update the truth file; up to 3 rounds, at most 5 agents at a time',
  phases: [
    { title: 'Round', detail: 'list the new errors (script, one agent)' },
    { title: 'Diagnose', detail: 'one agent per case (regression or mismatch mode)' },
    { title: 'Verify', detail: 'a skeptic per case' },
    { title: 'Update', detail: 'apply the outcomes to the truth file (script, one agent)' },
  ],
}

const PY = 'PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python'
const LIMIT = 5
let running = 0
const waiting = []
async function limited(fn) {
  while (running >= LIMIT) await new Promise(resolve => waiting.push(resolve))
  running++
  try { return await fn() } finally { running--; const next = waiting.shift(); if (next) next() }
}

const STATUS = { type: 'string', enum: ['agree', 'wrong', 'missing', 'unknown'] }
const RECORD = {
  type: 'object',
  properties: {
    case_id: { type: 'string' }, sec_id: { type: 'string' }, ticker: { type: 'string' }, report: { type: 'string' },
    mode: { type: 'string', enum: ['regression', 'mismatch'] },
    field_verdicts: { type: 'array', items: { type: 'object', properties: { field: { type: 'string' },
      right: { type: 'string', enum: ['old', 'new', 'truth', 'library', 'neither'] }, value: { type: 'string' },
      missed_filing: { type: 'string' } }, required: ['field', 'right', 'value', 'missed_filing'] } },
    confidence: { type: 'string', enum: ['verified', 'inferred', 'unresolved'] },
    status: { type: 'object', properties: { exit_kind: STATUS, last_trade_date: STATUS, successor: STATUS,
      value_rule: STATUS, terms: STATUS, issuer: STATUS, ticker_history: STATUS } },
    confidence_reasons: { type: 'array', items: { type: 'string' } },
    sec_evidence: { type: 'integer' }, web_evidence: { type: 'integer' }, verdict: { type: 'string' },
  },
  required: ['case_id', 'sec_id', 'mode', 'field_verdicts', 'confidence', 'confidence_reasons', 'sec_evidence',
    'web_evidence', 'verdict'],
}
const VERDICT = {
  type: 'object',
  properties: { case_id: { type: 'string' }, upheld: { type: 'boolean' },
    fields_upheld: { type: 'array', items: { type: 'string' } },
    fields_refuted: { type: 'array', items: { type: 'object', properties: { field: { type: 'string' },
      why: { type: 'string' } }, required: ['field', 'why'] } }, notes: { type: 'string' } },
  required: ['case_id', 'upheld', 'fields_upheld', 'fields_refuted', 'notes'],
}
// A runner agent returns the command's exit code and its last stdout line, verbatim; the script parses the line
// itself (an agent's transcription of a case list could drop or invent a case) and stops on a non-zero exit.
const RUN = { type: 'object', properties: { exit_code: { type: 'integer' }, stdout: { type: 'string' } },
  required: ['exit_code', 'stdout'] }
const ROUND = RUN
const UPDATE = RUN
const WRITTEN = { type: 'object', properties: { written: { type: 'array', items: { type: 'string' } } },
  required: ['written'] }

function runner(cmd) {
  return `Run exactly this one command from the repo root (your working directory) with the Bash tool, then return
its exit code as exit_code and its last stdout line, copied verbatim, as stdout (an empty string when it printed
nothing). Do not edit any file, fix anything or run anything else.

${cmd}`
}

function parsed(res, what) {
  if (!res) throw new Error(`${what}: the runner agent returned nothing`)
  if (res.exit_code !== 0) throw new Error(`${what} exited ${res.exit_code}: ${res.stdout}`)
  try { return JSON.parse(res.stdout) } catch (e) { throw new Error(`${what}: stdout is not JSON: ${res.stdout}`) }
}

function diagnosePrompt(c, dir) {
  return `Diagnose one ${c.mode} case of the delist_detection truth loop: ${c.case_id} (${c.ticker || 'no ticker'}).

Read first: .claude/skills/diagnose-delisting/SKILL.md (your instructions; its "Modes" section is your mode),
.claude/skills/diagnose-delisting/reference.md and .claude/skills/diagnose-delisting/example-THI.md.

Your case is the row of ${dir}/cases.csv whose case_id is ${c.case_id} (grep '^${c.case_id},' ${dir}/cases.csv;
header: head -1). Write exactly two files with the Write tool BEFORE you return:
${dir}/reports/${c.case_id}.md and ${dir}/records/${c.case_id}.json. Then return the record.

Four other agents share SEC's rate limit through the lock in sec.py; use only sec.py for SEC, with allowed_domains
data.sec.gov, www.sec.gov, efts.sec.gov. Do not edit any other file, run the pipeline, commit or dispatch subagents.`
}

function verifyPrompt(c, r, dir) {
  return `You are a skeptic checking one truth-loop diagnosis: ${dir}/reports/${c.case_id}.md (mode ${c.mode}).
Its field verdicts: ${JSON.stringify(r.field_verdicts)}.

Read the report, .claude/skills/diagnose-delisting/reference.md and the case row (grep '^${c.case_id},'
${dir}/cases.csv). For each field verdict, try to REFUTE it: re-open the cited filings through sec.py (SKILL.md
step 2), check dates, numbers, the security class and the rule. For a "library" verdict in mismatch mode, check that
the named missed_filing really shows the earlier report wrong. A verdict survives only if the evidence supports it.

Append "## 9. Verification" to the report and add a "verification" object (your result) to
${dir}/records/${c.case_id}.json. Edit only those two files. Return the result object.`
}

if (!args.label) throw new Error('diagnosis-truth-loop: args.label is missing')
if (!args.base) throw new Error('diagnosis-truth-loop: args.base is missing')
const label = args.label
const maxRounds = args.maxRounds || 3
const summaries = []
for (let round = 1; round <= maxRounds; round++) {
  const dir = args.casesPath ? args.casesPath.replace(/\/cases\.csv$/, '') :
    `output/diagnose_unknown_report/loop/${label}/round-${round}`
  let listed
  if (args.casesPath) {
    listed = parsed(await agent(runner(`${PY} -c "import csv,json; print(json.dumps({'mismatches_new': 0, 'regressions_new': 0, 'path': '${args.casesPath}', 'cases': [{'case_id': r['case_id'], 'mode': r['mode'], 'ticker': r['ticker']} for r in csv.DictReader(open('${args.casesPath}'))]}))"`),
      { label: 'round:prepared', phase: 'Round', schema: ROUND, model: 'sonnet', effort: 'low' }), 'round:prepared')
  } else {
    listed = parsed(await agent(runner(`${PY} scripts/truth_loop_round.py --label ${label} --base ${args.base} --round ${round}`),
      { label: `round:${round}`, phase: 'Round', schema: ROUND, model: 'sonnet', effort: 'low' }), `round ${round}`)
  }
  const dry = (args.dryRun || args.casesPath) ? ' --dry-run' : ''
  const update = async () => parsed(await agent(
    runner(`${PY} scripts/update_truth.py --label ${label} --round ${round} --base ${args.base}${dry}`),
    { label: `update:${round}`, phase: 'Update', schema: UPDATE, model: 'sonnet', effort: 'low' }), `update ${round}`)
  if (!listed.cases.length) {
    // No new error: the update step still runs on the empty cases.csv, so a known_wrong case the run now matches
    // becomes pass (flip_statuses), and then the loop stops.
    log(`round ${round}: no new errors`)
    summaries.push({ round, cases: 0, missing: [], update: await update() })
    break
  }
  log(`round ${round}: ${listed.cases.length} case(s) (${listed.mismatches_new} mismatches, ${listed.regressions_new} regressions)`)
  const done = await pipeline(listed.cases,
    c => limited(() => agent(diagnosePrompt(c, dir), { label: `diagnose:${c.ticker || c.case_id}`,
      phase: 'Diagnose', schema: RECORD, model: 'sonnet' })),
    (r, c) => r ? limited(() => agent(verifyPrompt(c, r, dir), { label: `verify:${c.ticker || c.case_id}`,
      phase: 'Verify', schema: VERDICT, model: 'sonnet' })).then(v => ({ record: r, verification: v })) : null)
  // update_truth.py reads the record files and treats a case without a complete one as failed: it changes nothing
  // and leaves no ledger row, so the next round diagnoses it again.
  const missing = listed.cases.filter((c, i) => !done[i] || !done[i].verification).map(c => c.case_id)
  if (missing.length) log(`round ${round}: no record or no verification for ${missing.join(', ')}: left out of the update, retried next round`)
  // An agent sometimes returns its result without writing it into the record file (the diagnose agent its record,
  // the verifier its verdict). The returned values are written back here when the file is missing or lacks a key.
  const returned = {}
  listed.cases.forEach((c, i) => {
    if (done[i] && done[i].verification) returned[c.case_id] = { record: done[i].record, verification: done[i].verification }
  })
  if (Object.keys(returned).length) {
    const wb = await agent(`For each case id below, check ${dir}/records/<case_id>.json. It is complete when it exists
and has all of the keys "field_verdicts", "confidence" and "verification". Leave a complete file untouched. Otherwise
write the file with the Write tool: when it is missing, the given "record" merged with the given "verification" (as
the key "verification"); when it exists, every key it has, plus each of those three keys it lacks taken from the given
values (field_verdicts and confidence from "record", verification from "verification"). Edit nothing else. Return the
list of case ids you wrote.

${JSON.stringify(returned, null, 1)}`,
      { label: `writeback:${round}`, phase: 'Update', schema: WRITTEN, model: 'sonnet', effort: 'low' })
    log(`round ${round}: wrote ${wb ? wb.written.length : 0} record(s) back into the files`)
  }
  summaries.push({ round, cases: listed.cases.length, missing, update: await update() })
  if (args.casesPath) break
}
return { label, rounds: summaries }
