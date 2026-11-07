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
- [ ] Step 20: Verified Query Library and Feedback Loop (guide received)
- [ ] Step 21: (title added when the guide arrives)
- [ ] Step 22: (title added when the guide arrives)
- [ ] Step 23: (title added when the guide arrives)
- [ ] Step 24: (title added when the guide arrives)
- [ ] Step 25: (title added when the guide arrives)
- [ ] Step 26: Full documentation (per the README stub)

## What is left

- Steps 20 to 26 (guide for Step 20 received).
- UI placeholders to fill: Admin › Monitoring, Review (verify / correct queries,
  not-helpful answers) and Evaluation (Steps 20-22).
- Deferred (agreed with the user): the live end-to-end check of the UI and the remaining
  screenshots in `docs/screenshots/` (only `01-login.jpg` so far). Done once after Step 22,
  when Monitoring, Review and Evaluation are filled in: the user signs in as
  `sales.europe`, `finance`, `admin` and `no.role` in the browser pane (the assistant does
  not read demo passwords), then every screen is exercised and captured.
- API endpoints that return 501 until their step: `GET /admin/metrics` (dashboard),
  `GET/POST /admin/verified-queries` (Step 20), `POST /admin/eval/run` and
  `GET /admin/eval/runs` (evaluation). Their final request and response models exist.
- Rate limits are in memory (one API process); a shared store is needed before running
  several API workers.
- For later steps: wire `validate_question` and `validate` into the graph (N-02, N-07)
  and store blocks in `app.blocked_queries` with their `BlockReason`. Columns the
  semantic layer does not describe are refused by the validator; add them to the YAML if
  eval questions need them. The LLM provider and the `checkpoints` schema grants are still to come.
- Settled in Step 2 (see `docs/design/data-decisions.md`): +27-year date shift, business
  reference date 2025-05-06, region mapping (Rest of World = Brazil, Argentina, Venezuela).
- Still open:
  - The LLM model must be pinned to a dated version before evaluation runs.
  - Draft evaluation cases have 27 of the 60+ required; correct SQL is written in Step 22.
