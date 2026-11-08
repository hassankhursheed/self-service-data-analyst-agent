# Screenshots

AskData on the local Docker Compose stack (Step 26), light theme unless noted, desktop
1366 x 860 unless noted. Only fictional Northwind Traders data; no passwords, keys or
tokens are visible.

| File | Shows |
| --- | --- |
| `01-login.png` | Sign-in page: product name, tagline, trust points, dataset note |
| `02-ask-start.png` | Ask screen as `sales.europe`: scope chip "Europe · read-only", dataset label, role-based suggestions |
| `03-progress-steps.png` | The agent's steps while a question runs |
| `04-answer-ranked-list.png` | Structured answer: summary first, then the rows as a ranked list (names, values, details) |
| `05-answer-verified-metric.png` | A single-value answer with the "Verified against the data" badge, period, CSV link and assumptions |
| `06-blocked-write.png` | "Delete all orders from 2023" blocked with the reason (write request) |
| `07-access-control-attempt.png` | The Europe sales manager asks for USA revenue: the database returns nothing, the answer says so |
| `08-audit-trail.png` | Stored audit trail of one question: correlation ID, user, role, region, period, versions, tokens, cost, node steps (read from the app schema) |
| `09-audit-sql-and-events.png` | Same trail: the generated SQL, the role and region it ran under (`analytics_ro`, `sales_ro`, EUROPE), rows, and the audit event |
| `10-history.png` | Previous conversations |
| `11-admin-users.png` | Admin: users, roles, regions, status, actions |
| `12-admin-monitoring.png` | Admin: monitoring metrics (outcomes, latency, cost, ratings, failed logins, latest evaluation) |
| `13-admin-monitoring-steps.png` | Admin: time per agent node, questions by role, blocked queries by reason, recent alerts |
| `14-admin-review-blocked.png` | Admin: review queue filtered to blocked queries |
| `15-admin-verified-library.png` | Admin: verified query library |
| `16-admin-evaluation.png` | Admin: start an evaluation run, compare runs |
| `17-dark-theme.png` | The ranked-list answer in the dark theme |
| `18-mobile-answer.png` | Phone width (375 px): the ranked list |
| `19-mobile-admin-users.png` | Phone width: users as cards with full-size actions |

The audit-trail views (08, 09) are rendered from the database tables for the screenshot;
the app itself has no audit-log page (the trail is in `app.questions`, `app.agent_runs`,
`app.agent_steps`, `app.generated_queries`, `app.query_executions` and `app.audit_log`).
A LangSmith trace screenshot needs the owner's LangSmith login and is added separately.
