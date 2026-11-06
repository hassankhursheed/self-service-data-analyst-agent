# Architecture

Brief sections 4, 5 and 27. One FastAPI service hosts a LangGraph graph of small nodes; one
PostgreSQL database holds the Northwind data and the application data in separate schemas.

## Diagram

```mermaid
flowchart LR
    user(["Business user or admin (browser)"])

    subgraph hosting["Hosting: Docker Compose locally, HTTPS host for the live demo"]
        ui["Next.js UI (React, TypeScript, Tailwind)"]

        subgraph api["FastAPI service (async)"]
            routes["API routes: JWT check, correlation ID, rate limit"]

            subgraph agent["LangGraph agent"]
                n01["N-01 Request Intake"]
                n02["N-02 Input Guardrails"]
                n03["N-03 Intent and Ambiguity"]
                n04["N-04 Clarification"]
                n05["N-05 Context Retrieval"]
                n06["N-06 SQL Generation"]
                n07["N-07 SQL Validation and Policy"]
                n08["N-08 Execution"]
                n09["N-09 Repair"]
                n10["N-10 Answer and Visualization"]
                n11["N-11 Audit and Metrics"]
            end
        end

        subgraph pg["PostgreSQL"]
            northwind[("public: Northwind tables (read-only to the app)")]
            analytics[("analytics: region map; sales_ro / finance_ro / operations_ro: secure views")]
            appdb[("app: application schema")]
            checkpoints[("checkpoints: LangGraph state")]
        end
    end

    llm[["LLM provider"]]
    langsmith[["LangSmith"]]
    ci[["GitHub Actions CI"]]

    user -->|A1| ui
    ui -->|A2| routes
    routes -->|A3| n01
    routes -->|A4| appdb
    n01 --> n02 --> n03
    n03 -->|A5| n04
    n03 --> n05 --> n06 --> n07
    n07 -->|A6| n08
    n08 -->|A7| n09
    n09 --> n07
    n08 --> n10 --> n11
    n05 -->|A8| appdb
    agent -->|A9| llm
    n08 -->|A10| northwind
    northwind -.->|A11| analytics
    n11 -->|A12| appdb
    agent -->|A13| checkpoints
    agent -->|A14| langsmith
    ci -->|A15| hosting
```

## Arrows

| Arrow | Meaning |
| --- | --- |
| A1 | The user logs in and asks questions in the Next.js UI over HTTPS; its server routes forward calls to the API and keep the token in an httpOnly cookie. |
| A2 | The UI calls the REST API with a bearer JWT; every response returns the correlation ID. |
| A3 | Ask and clarify requests start a graph run; role and region come from the token and the database, never from the question. |
| A4 | Login, users, conversations, feedback and admin screens read and write the `app` schema with the `app_rw` role. |
| A5 | An ambiguous question stops at N-04, which returns one clarifying question and waits for the user. |
| A6 | Only SQL that passed parsing, allow-lists and limits reaches execution; blocked SQL stops with a reason. |
| A7 | A database error goes to N-09, which repairs the SQL (max 2 attempts) and sends it back through validation. |
| A8 | N-05 reads the semantic catalog, metric definitions, business calendar and verified examples. |
| A9 | N-02, N-03, N-06, N-09 and N-10 call the LLM with schema, definitions and only the result rows needed; no sensitive personal data. |
| A10 | N-08 runs SQL as the read-only `analytics_ro` login against the role's secure views, with `SET LOCAL app.user_role`, `app.user_region` (from the token), a statement timeout and a row limit. |
| A11 | The secure views read Northwind tables with only the allowed columns and keep a sales manager's rows by looking up the region map. |
| A12 | N-11 writes the audit trail, per-node steps, latency, tokens, cost and the final status. |
| A13 | The PostgreSQL checkpointer stores conversation state per user and session, so follow-ups work. |
| A14 | Every run is traced in LangSmith; the trace is linked to the question by correlation ID. |
| A15 | CI runs unit tests, integration tests and an evaluation subset on every push, and blocks a release if any check fails. |

## Responsibilities and trust boundaries

- **UI** shows results only; it holds no business logic and no database credentials.
- **API routes** authenticate, assign the correlation ID, apply rate limits and map
  graph results to response models.
- **Graph nodes** each do one job (see `langgraph-design.md`) and are tested on their own.
- **Safety is enforced twice:** in code (N-07 validation) and in the database (read-only
  login, row-level security, column grants). The prompt is never the only control.
- **Two database logins:** `app_rw` for application data and `analytics_ro` (read-only)
  for Northwind queries. The agent process never holds write credentials for Northwind.
- **Secrets** come from environment variables only (see `.env.example`).
