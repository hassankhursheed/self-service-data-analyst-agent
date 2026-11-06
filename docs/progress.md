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
- [ ] Step 13: (title added when the guide arrives)
- [ ] Step 14: (title added when the guide arrives)
- [ ] Step 15: (title added when the guide arrives)
- [ ] Step 16: (title added when the guide arrives)
- [ ] Step 17: (title added when the guide arrives)
- [ ] Step 18: (title added when the guide arrives)
- [ ] Step 19: (title added when the guide arrives)
- [ ] Step 20: (title added when the guide arrives)
- [ ] Step 21: (title added when the guide arrives)
- [ ] Step 22: (title added when the guide arrives)
- [ ] Step 23: (title added when the guide arrives)
- [ ] Step 24: (title added when the guide arrives)
- [ ] Step 25: (title added when the guide arrives)
- [ ] Step 26: Full documentation (per the README stub)

## What is left

- Steps 13 to 26 (Step 13 plan is waiting for approval; guides for Steps 14-15 received).
- For later steps: wire `validate_question` and `validate` into the graph (N-02, N-07)
  and store blocks in `app.blocked_queries` with their `BlockReason`. Columns the
  semantic layer does not describe are refused by the validator; add them to the YAML if
  eval questions need them. The LLM provider and the `checkpoints` schema grants are still to come.
- Settled in Step 2 (see `docs/design/data-decisions.md`): +27-year date shift, business
  reference date 2025-05-06, region mapping (Rest of World = Brazil, Argentina, Venezuela).
- Still open:
  - The LLM model must be pinned to a dated version before evaluation runs.
  - Draft evaluation cases have 27 of the 60+ required; correct SQL is written in Step 22.
