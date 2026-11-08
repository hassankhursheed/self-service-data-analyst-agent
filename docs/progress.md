# Progress

The project is built in 26 steps. Titles for later steps are added when each step guide arrives.

- [x] Step 1: Project Setup and Standing Rules (Week 1, brief sections 3, 5, 27)
- [x] Step 2: Design Checkpoint Documents (Week 1, brief sections 4, 5, 11, 19, 21, 32)
- [x] Step 3: Docker Compose and Northwind Load (Week 1, brief sections 6, 29)
- [x] Step 4: Application Schema and Migrations (Week 1, brief section 21)
- [x] Step 5: Seed Script, Date Shift, Regions and Test Users (Week 1, brief sections 6, 7)
- [x] Step 6: Database Roles, Row-Level Security and Sensitive Columns (Week 1, brief sections 12, 13, 27)
- [x] Step 7: Semantic Layer (Week 1, brief section 9)
- [x] Step 8: Business Calendar and Date Resolution (Week 1, brief section 10)
- [x] Step 9: SQL Safety Validator (Week 1, brief section 12)
- [x] Step 10: LLM Client, Retries, Timeouts and Budgets (Week 2, brief sections 22, 27)
- [x] Step 11: LangGraph State, Transitions, Intake and Guardrails (Week 2, brief sections 4, 5, 11)
- [x] Step 12: Intent, Ambiguity and Clarification (Week 2, brief section 14)
- [x] Step 13: Context Retrieval, SQL Generation, Execution and Repair (Week 2, brief sections 12, 13, 15)
- [x] Step 14: Grounded Answers and Charts (Week 2, brief section 17)
- [x] Step 15: Conversation Memory and Follow-ups (Week 2, brief section 18)
- [x] Step 16: Audit Log, Error Records and Tracing (Week 2, brief sections 22, 23)
- [x] Step 17: Authentication and User Management (Week 3, brief section 8)
- [x] Step 18: FastAPI Endpoints (Week 3, brief sections 19, 22)
- [x] Step 19: User Interface (Week 3, brief section 20)
- [x] Step 20: Verified Query Library and Feedback Loop (Week 3, brief section 16)
- [x] Step 21: Monitoring Dashboard (Week 3, brief section 26)
- [x] Step 22: Evaluation Set and Experiments (Week 4, brief section 24)
- [x] Step 23: Automated Tests and CI Pipeline (Week 3-4, brief section 25)
- [x] Step 24: Security, Privacy and Performance Hardening (Week 4, brief sections 27, 28)
- [ ] Step 25: Live Deployment (built and tested locally: production images, one-command
  Compose, demo reset, daily cost cap, Railway setup in docs/deployment.md; left: the user
  deploys on Railway, then the live HTTPS check with the demo accounts, scenario 28)
- [ ] Step 26: Recommended Extras, Final Docs and Full Verification (Part A done: EXPLAIN
  cost check, CSV export, alerts, 90-day log clean-up, 20-user load test (eval/LOAD_TEST.md);
  left: Part B final docs and screenshots, Part C the 28 scenarios and deliverables)

## What is left

- Evaluation (eval/RESULTS.md): 77.5% accuracy with verified examples (target 80%), 100%
  clarification, 0 leaks, 83.3% unsafe blocked (one malformed reply, nothing executed),
  5 ungrounded (all date fragments). Follow-ups: dates as grounded context in the
  grounding check, a system-catalog rule in the question guardrails, tell the SQL prompt
  region filtering is already applied, a stronger model on a paid plan.
- Step 25: the user creates the Railway project (docs/deployment.md), then the live HTTPS
  URL is checked with the demo accounts (scenario 28).
- Step 26 Part B (README, api.md, setup guide, screenshots, demo script) and Part C (all
  28 scenarios with correlation IDs, Section 31 checklist), done with the local run.
- Security follow-ups (docs/security.md, What is left): shared rate-limit store before
  several API workers, alias-proof personal-column detection, a secret scanner in CI.
- CI `live-eval` runs only once the `LLM_API_KEY` repository secret is added on GitHub
  (Settings → Secrets and variables → Actions); until then it is skipped with a notice.
- Results go in the README too (brief §24), in Step 26.
- Deferred (agreed with the user): the live end-to-end check of the UI and the remaining
  screenshots in `docs/screenshots/` (only `01-login.jpg` so far). Done once after Step 22,
  when Monitoring, Review and Evaluation are filled in: the user signs in as
  `sales.europe`, `finance`, `admin` and `no.role` in the browser pane (the assistant does
  not read demo passwords), then every screen is exercised and captured.
- Rate limits are in memory (one API process); a shared store is needed before running
  several API workers.
- Settled in Step 2 (see `docs/design/data-decisions.md`): +27-year date shift, business
  reference date 2025-05-06, region mapping (Rest of World = Brazil, Argentina, Venezuela).
- Still open:
  - Model: `ministral-14b-2512` for the app and the evaluation (free credits refuse
    Mistral Small / Medium). Revisit when a paid plan is available.
