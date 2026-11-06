# Progress

The project is built in 26 steps. Titles for later steps are added when each step guide arrives.

- [x] Step 1: Project Setup and Standing Rules (Week 1, brief sections 3, 5, 27)
- [x] Step 2: Design Checkpoint Documents (Week 1, brief sections 4, 5, 11, 19, 21, 32)
- [x] Step 3: Docker Compose and Northwind Load (Week 1, brief sections 6, 29)
- [x] Step 4: Application Schema and Migrations (Week 1, brief section 21)
- [ ] Step 5: (title added when the guide arrives)
- [ ] Step 6: (title added when the guide arrives)
- [ ] Step 7: (title added when the guide arrives)
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

- Steps 5 to 26.
- From Steps 3-4, for later steps: database roles (`app_rw`, `agent_login`, `*_ro`), RLS,
  the date shift and region mapping are not applied yet. Locally `APP_DATABASE_URL` points
  at the owner account until the `app_rw` role exists.
- Settled in Step 2 (see `docs/design/data-decisions.md`): +27-year date shift, business
  reference date 2025-05-06, region mapping (Rest of World = Brazil, Argentina, Venezuela).
- Still open:
  - The LLM provider is not chosen yet.
  - Draft evaluation cases have 27 of the 60+ required; correct SQL is written in Step 22.
  - Full business-calendar rules (beyond the key rules in data-decisions.md).
