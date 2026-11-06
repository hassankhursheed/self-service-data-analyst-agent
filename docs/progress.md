# Progress

The project is built in 26 steps. Titles for later steps are added when each step guide arrives.

- [x] Step 1: Project Setup and Standing Rules (Week 1, brief sections 3, 5, 27)
- [x] Step 2: Design Checkpoint Documents (Week 1, brief sections 4, 5, 11, 19, 21, 32)
- [x] Step 3: Docker Compose and Northwind Load (Week 1, brief sections 6, 29)
- [x] Step 4: Application Schema and Migrations (Week 1, brief section 21)
- [x] Step 5: Seed Script, Date Shift, Regions and Test Users (Week 1, brief sections 6, 7)
- [x] Step 6: Database Roles, Row-Level Security and Sensitive Columns (Week 1, brief sections 12, 13, 27)
- [x] Step 7: Semantic Layer (Week 1, brief section 9)
- [ ] Step 8: (title added when the guide arrives)
- [ ] Step 9: (title added when the guide arrives)
- [ ] Step 10: (title added when the guide arrives)
- [ ] Step 11: (title added when the guide arrives)
- [ ] Step 12: (title added when the guide arrives)
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

- Steps 8 to 26.
- For later steps: SQL validation (allow-lists from `config/access_policy.yaml`) must
  reject `SET`, `set_config` and system catalogs before execution; the database already
  refuses them, but validation gives the user a clear reason. Business calendar rules,
  the LLM provider and the `checkpoints` schema grants are still to come.
- Settled in Step 2 (see `docs/design/data-decisions.md`): +27-year date shift, business
  reference date 2025-05-06, region mapping (Rest of World = Brazil, Argentina, Venezuela).
- Still open:
  - The LLM provider is not chosen yet.
  - Draft evaluation cases have 27 of the 60+ required; correct SQL is written in Step 22.
  - Full business-calendar rules (beyond the key rules in data-decisions.md).
