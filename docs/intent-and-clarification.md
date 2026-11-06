# Intent, ambiguity and clarification (N-03, N-04)

Brief sections 10 and 14. The agent never silently guesses when the answer would change.

## N-03 Intent and Ambiguity

1. **LLM analysis.** The prompt `config/prompts/intent/v1.yaml` gives the model the
   business date, the metrics and tables the user's role may use, the question and any
   earlier clarifications. The model returns one JSON object, validated by the Pydantic
   model `IntentAnalysis` (`app/agent/intent.py`): metric, metric options, time phrase,
   entities, grouping, top N, missing parts, small assumptions, and a suggested clarifying
   question with options.
2. **Malformed output.** If the reply is not valid JSON or does not match the model, the
   problem is sent back once and the model answers again (`ainvoke_structured`,
   `app/core/llm.py`). A second invalid reply ends the question as `FAILED` with
   *"I could not produce a reliable answer to this question. Please try rephrasing it."*
   (`MalformedOutput`). Never more than one regeneration.
3. **Decision in code** (`decide`, rules in `config/agent.yaml`), not by the model:

| Situation | Outcome | Example |
| --- | --- | --- |
| Nothing important missing, time phrase resolved | **clear**: continue (`UNDERSTOOD`) | "Revenue last quarter" -> "Last quarter = 1 Jan to 31 Mar 2025" |
| Only the time range or top N missing | **minor assumption**: continue, state it | "Revenue by category" -> "No time period given: assumed This year = 1 Jan to 6 May 2025." |
| Named month/quarter without a year | **minor assumption** from the calendar | "Revenue in March" -> "No year given: used the most recent March." |
| Metric, entity or grouping missing | **ambiguous**: ask (`CLARIFICATION_NEEDED`) | "Top customers" -> "Top customers by revenue or by number of orders, and for which year?" |
| Time phrase the calendar cannot resolve | counted as missing time | "since forever" |

When the agent asks, it asks about **everything** missing in one question (metric and
year together), with 2 to 4 options. The model's own question is used when it has 2 to 4
options; otherwise a fixed template is used.

Time phrases are always resolved with the business calendar (`docs/business-calendar.md`),
never the real date.

## N-04 Clarification and resume

- N-04 pauses the graph with a LangGraph `interrupt`, returning the question, the options,
  the round number and the missing parts. The question stays `CLARIFICATION_NEEDED` and
  `awaiting_reply` is true.
- `Agent.resume(thread_id, reply)` continues the same thread. N-04 stores a
  `ClarificationRecord` (round, question, options, missing parts, asked/answered times and
  the reply, an option or free text) and hands back to N-03, which analyses the question
  again with the reply included and normally reaches `UNDERSTOOD`.
- **Rounds:** one round normally; a second only if the reply is still unclear
  (`max_clarification_rounds: 2`). If it is still unclear after that, the question ends as
  `FAILED` with a message asking the user to include the measure and the period.
- Clarifications and assumptions are kept in the state (`clarifications`, `assumptions`)
  for the clarifications table and the answer (later steps).
- The checkpointer is in memory for now; Step 15 replaces it with PostgreSQL so a pause
  survives restarts and threads are scoped to the user.
