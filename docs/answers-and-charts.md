# Grounded answers and charts (N-10)

Brief section 17. Answers only state numbers that exist in the query result.

Code: `app/agent/nodes/answer.py` (node), `app/agent/grounding.py` (check),
`app/agent/charts.py` (chart rules), `app/agent/response.py` (response model).
Settings: `answer` in `config/agent.yaml`. Prompt: `config/prompts/answer/v1.yaml`.

## How an answer is made

1. **Empty result:** no LLM call. The answer is *"No orders matched these filters
   (2024 = 1 Jan to 31 Dec 2024). Try a broader question, for example a longer period or
   fewer filters."* The noun comes from the main table of the query (order lines for
   `order_details`).
2. **Otherwise** the LLM receives the question, period, assumptions, the SQL and only the
   **first 20 rows** (`rows_for_llm`). The columns are already limited to the user's role
   by the validator and the secure views. It returns JSON: `explanation` (1-3 sentences)
   and `sql_description` (one plain sentence).
3. **Grounding check** on the explanation. If a number is not grounded, the list of bad
   numbers is sent back and the model writes it once more (`max_regenerations: 1`).
4. **Fallback:** still ungrounded, malformed, over budget or the LLM is unavailable, so the
   answer is a plain template built from the rows, for example *"The query returned 8 rows
   for 2024 = 1 Jan to 31 Dec 2024. Top results: category name Beverages, revenue
   10,000; ..."*. The rows are correct, so the question is still `ANSWERED`.

`answer.source` records which path was used: `llm`, `template` or `empty`.

## Grounding rules (documented allowances)

Every number written in the explanation must match one of:

| Allowed | Example (result value) | Accepted text |
| --- | --- | --- |
| A result value, rounded to the precision written | 12345.678 | "12,345.68", "about 12,346" |
| Thousands separators, currency sign | 12345.678 | "$12,345.68" |
| Scale words and suffixes | 12345.678 | "12.3k"; 1,234,567 -> "1.2 million" |
| A percentage given as a value | 37.5 (a `share` column) | "37.5%" |
| A fraction shown as a percentage | 0.375 | "37.5%" |
| A share of its column total | 40 of 100 orders | "40%" |
| The change between two values of a column | 40 -> 60 | "50% more" |
| Context numbers | row count, top N, numbers in the question, the resolved period (years, days) and assumptions | "In 2024 the top 5..." |

Anything else fails the check, including sums or estimates the model computed itself.
Tolerance is half a unit of the last digit written (times the scale).

## Chart rules

`choose_chart(columns, rows, truncated, config)` is a pure function:

| Shape | Chart |
| --- | --- |
| No rows, or the result was cut at the row limit | none |
| One row with one numeric value | metric card |
| A time column (date values, or a name with date/day/week/month/quarter/year/period) plus numeric columns, 2 to 400 rows | line (sorted by time) |
| A text column plus numeric columns, 2 to 30 rows | bar |
| More than 30 categories or 400 points, or no numeric column | none (the table is shown) |

At most 3 numeric series (`max_series`). The spec is neutral (`type`, `x`, `y`, `data`
as JSON records, `title`, `reason`); the Next.js UI draws it.

## Response model

`build_response(state, page, page_size)` returns `AgentResponse` with: correlation ID,
thread ID, status, message, answer text, `low_confidence` and the label, chart spec, a page
of the table (`page`, `page_size`, `total_rows`, `total_pages`, `truncated`), row count, SQL
(the text that ran and its one-line description), assumptions, the resolved date range,
notices (for example the scope-override notice), a pending clarification, or the block
reason. For an answered question the SQL, description, assumptions, date range and row
count are always present.
