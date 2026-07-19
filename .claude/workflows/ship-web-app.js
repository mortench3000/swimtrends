export const meta = {
  name: 'ship-web-app',
  description: 'One human-gated iteration of end-to-end web-app dev: orient -> implement (TDD) -> test -> review -> fix, optional gated deploy+smoke-test',
  whenToUse: 'Drive end-to-end development of the Swimtrends web app. Run repeatedly (outer loop is you + user approval). Pass args.goal on first run; args.deploy:true only AFTER human approval.',
  phases: [
    { title: 'Orient', detail: 'read/boot plan, pick this iteration\'s tasks' },
    { title: 'Implement', detail: 'TDD each task sequentially' },
    { title: 'Test', detail: 'pytest + CDK unit tests' },
    { title: 'Review', detail: 'code-reviewer over the diff' },
    { title: 'Fix', detail: 'address findings, re-test' },
    { title: 'Deploy', detail: 'gated: cdk deploy + live smoke test' },
  ],
}

// ponytail: one workflow, one iteration. The outer "keep going until satisfactory"
// loop is the human-approval gate the user chose — not baked in here (background
// runs can't prompt, and CLAUDE.md forbids unattended deploys).

const REPO = '/home/mortench/keycore/repos/mortench3000/swimtrends'
const PLAN = `${REPO}/docs/superpowers/web-app-plan.md`
const goal = (args && args.goal) || 'Build a web frontend/API over the curated Swimtrends analytics data, deployed to AWS.'
const doDeploy = !!(args && args.deploy)

const ORIENT = {
  type: 'object', additionalProperties: false,
  required: ['done', 'tasks', 'notes'],
  properties: {
    done: { type: 'boolean', description: 'true if the plan is fully implemented and nothing remains for this iteration' },
    tasks: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['title', 'detail'],
      properties: { title: { type: 'string' }, detail: { type: 'string', description: 'concrete, testable scope for one task' } } } },
    notes: { type: 'string' },
  },
}
const TASK = {
  type: 'object', additionalProperties: false,
  required: ['title', 'summary', 'files'],
  properties: {
    title: { type: 'string' },
    summary: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
  },
}
const TESTS = {
  type: 'object', additionalProperties: false,
  required: ['passed', 'summary'],
  properties: { passed: { type: 'boolean' }, summary: { type: 'string' }, failures: { type: 'string' } },
}
const REVIEW = {
  type: 'object', additionalProperties: false,
  required: ['findings'],
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false,
    required: ['severity', 'file', 'issue'],
    properties: { severity: { type: 'string', enum: ['blocker', 'major', 'minor'] }, file: { type: 'string' }, issue: { type: 'string' } } } } },
}
const DEPLOY = {
  type: 'object', additionalProperties: false,
  required: ['deployed', 'healthy', 'detail'],
  properties: { deployed: { type: 'boolean' }, healthy: { type: 'boolean' }, url: { type: 'string' }, detail: { type: 'string' } },
}

// --- Orient -------------------------------------------------------------
phase('Orient')
const orient = await agent(
  `You are orienting one iteration of building the Swimtrends web app.
Repo root: ${REPO}. Read CLAUDE.md, docs/, and the plan at ${PLAN} if it exists.
Goal: ${goal}
If ${PLAN} does NOT exist, first design a concrete, minimal plan (stack choice, phases, deploy target on AWS via the existing CDK app in swimtrends-app/) and WRITE it to ${PLAN}. Keep it lazy: prefer static-site-over-server, native/stdlib over deps, reuse the existing curated Parquet/DuckDB data path.
Then run 'git -C ${REPO} log --oneline -15' and inspect current state to decide which tasks remain.
Return the next 1-4 concrete tasks for THIS iteration (or done:true if the plan is fully shipped).`,
  { phase: 'Orient', schema: ORIENT, agentType: 'general-purpose' }
)

if (!orient || orient.done || !orient.tasks || orient.tasks.length === 0) {
  return { status: 'nothing-to-do', orient }
}
log(`Iteration plan: ${orient.tasks.map(t => t.title).join(' | ')}`)

// --- Implement (sequential: tasks share files) --------------------------
phase('Implement')
const implemented = []
for (let i = 0; i < orient.tasks.length; i++) {
  const t = orient.tasks[i]
  const r = await agent(
    `Repo root: ${REPO}. Implement this task using strict TDD (write the failing test first, watch it fail, then implement). Follow CLAUDE.md conventions and the superpowers:test-driven-development workflow.
Task: ${t.title}
Detail: ${t.detail}
Prior tasks this iteration: ${implemented.map(x => x.title).join(', ') || 'none'}
Be lazy (ponytail): shortest working diff, stdlib/native first, no speculative abstractions. Run the relevant tests before returning.`,
    { label: `impl:${t.title}`.slice(0, 48), phase: 'Implement', schema: TASK, agentType: 'general-purpose' }
  )
  if (r) implemented.push(r)
}

// --- Test ---------------------------------------------------------------
phase('Test')
const tests = await agent(
  `Repo root: ${REPO}. Run the full test suites and report honestly.
  cd ${REPO}/st-scrape && .venv/bin/python -m pytest -q
  cd ${REPO}/swimtrends-app && .venv/bin/python -m pytest tests/unit
Include any new web-app tests. Return passed=true ONLY if everything is green; put failing output in failures.`,
  { phase: 'Test', schema: TESTS, agentType: 'general-purpose' }
)

// --- Review -------------------------------------------------------------
phase('Review')
const review = await agent(
  `Review the current uncommitted diff in ${REPO} (run 'git -C ${REPO} diff' and 'git -C ${REPO} status'). Focus on correctness, silent failures, and over-engineering (ponytail). Report only real findings.`,
  { phase: 'Review', schema: REVIEW, agentType: 'pr-review-toolkit:code-reviewer' }
)

// --- Fix (blockers/majors only) -----------------------------------------
const mustFix = (review && review.findings || []).filter(f => f.severity !== 'minor')
let refix = null
if (mustFix.length) {
  phase('Fix')
  refix = await agent(
    `Repo root: ${REPO}. Address these review findings, then re-run the relevant tests (pytest in st-scrape, CDK unit tests) and confirm green:
${mustFix.map(f => `- [${f.severity}] ${f.file}: ${f.issue}`).join('\n')}
Keep fixes minimal.`,
    { phase: 'Fix', schema: TESTS, agentType: 'general-purpose' }
  )
}

// --- Deploy (gated) -----------------------------------------------------
let deploy = null
if (doDeploy) {
  phase('Deploy')
  deploy = await agent(
    `Repo root: ${REPO}. Human approval has been granted. Deploy per the CLAUDE.md runbook EXACTLY:
  export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
  cd ${REPO}/swimtrends-app
  export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
  cdk deploy <the web-app stack> --app ".venv/bin/python3 app.py" -c alert_email=mortench.privat@gmail.com --require-approval never
ALWAYS pass -c alert_email (omitting it drops the SNS subscription). Docker must be running.
After deploy, smoke-test the live URL (curl the health/root endpoint) and report the URL + HTTP status. Set healthy=true only on a 2xx response.`,
    { phase: 'Deploy', schema: DEPLOY, agentType: 'general-purpose', effort: 'high' }
  )
}

return {
  status: 'iteration-complete',
  goal,
  planFile: PLAN,
  implemented: implemented.map(t => t.title),
  tests,
  reviewFindings: review && review.findings,
  fixResult: refix,
  deploy,
  deployGate: doDeploy ? 'ran' : 'skipped (awaiting human approval; re-run with args.deploy:true)',
}
