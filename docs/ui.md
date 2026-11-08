# User interface

The UI (brief §20) is a Next.js (App Router) + React + TypeScript + Tailwind CSS app in
`ui/`. It talks only to the FastAPI service, never to the database, and holds no business
rules: role, region and permissions always come from the API.

## Run it

Local development (API on the host):

```bash
docker compose up -d                 # database
python scripts/run_api.py            # API on http://127.0.0.1:8000
npm --prefix ui install              # once
npm --prefix ui run dev              # UI on http://localhost:3000
```

Whole stack in Docker (run `python -m scripts.seed` once from the host first):

```bash
docker compose --profile app up -d --build   # db + api (8000) + ui (3000)
```

Checks:

```bash
npm --prefix ui run lint
npm --prefix ui run typecheck
npm --prefix ui test
npm --prefix ui run build
```

## Security model

```
browser ──(same-origin, httpOnly cookie)──> Next.js server routes ──(Bearer token)──> FastAPI
```

- **The token never reaches page JavaScript.** `POST /api/session` calls `/auth/login`
  and stores the token in an `httpOnly`, `SameSite=Strict` cookie (`Secure` in
  production). The browser receives only the user's name, role and region.
- **One narrow proxy.** `/api/proxy/<path>` forwards to the API with the token. Only the
  API paths the UI uses are allowed (`ui/src/lib/server/config.ts`); login, docs and
  anything else answer 404.
- **CSRF.** Besides `SameSite=Strict`, state-changing calls must be same-origin JSON.
- **Fresh identity.** The app layout calls `GET /auth/me` on every page load, so a role
  change or a disabled account takes effect at once. A 401 from the API clears the cookie
  and sends the user to the login screen.
- **Admin pages, three layers.** Non-admins do not see the admin links, the `/admin/*`
  layout redirects anyone who is not an admin on the server, and the API refuses every
  `/admin` call with 403.
- `API_BASE_URL` is a server-only setting; the browser never learns where the API is.
  Security headers: `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`.

## Screens

| Screen | Path | What it shows |
| --- | --- | --- |
| Login | `/login` | Username and password, clear errors (wrong credentials, too many attempts, expired session) |
| Ask & answer | `/` (`/?c=<id>` continues a conversation) | Question box with examples per role; answer text, low-confidence label, chart from the chart spec (line, bar, metric card), paginated result table, row count, date range, assumptions and notes, the SQL with its plain-language description, clarifying-question options as buttons (plus free text), helpful / not helpful with an optional comment, a short reference ID |
| Outcomes | (inside the answer) | Friendly cards for BLOCKED (with the reason), REJECTED and FAILED |
| History | `/history` | The user's own conversations, newest first; open one to see its questions and the latest answer, and keep asking |
| Admin › Users | `/admin/users` | Filter by role and status; create a user; change role and region (sales managers need a region); disable / enable; reset password |
| Admin › Review | `/admin/review` | Review queue (not-helpful answers, blocked queries, failures) with Verify or correct, Make eval case and Re-run; Verified library with versions, roles, Correct (new version) and Enable / Disable |
| Admin › Monitoring | `/admin/monitoring` | Period picker (today, 7 / 30 days, custom); metric cards, outcomes per day chart, questions by role, blocked by reason, latest evaluation run (docs/monitoring.md) |
| Admin › Evaluation | `/admin/evaluation` | Start a run (name, verified examples, semantic mode, case types); runs with progress; compare up to three runs against the targets; open a run for every case with SQL, answer and expected vs actual rows (docs/evaluation.md) |

The header always shows the user, their role and region, and a logout button. Admins
only see the admin pages (business questions are off for them, brief §8); a user without
a role sees a "no data access" message.

## Design

- Indigo accent, slate neutrals, semantic colours for status; light and dark mode follow
  the operating system.
- Responsive: the sidebar becomes a drawer below 1024 px, and tables scroll horizontally.
- Charts use Recharts with theme-aware colours; the API decides the chart type.

## API additions for the UI

- `GET /auth/me`: the caller with their current role and region.
- `GET /conversations/{id}/table?page=&page_size=`: one page of the latest question's
  rows (the table is paginated without re-running the query).

## Limitations

- Paging of the result table is available for the latest question of a conversation
  only; earlier questions show their first page.
- `npm audit` reports moderate advisories in development-only lint packages
  (`@typescript-eslint`); nothing in the production bundle.
