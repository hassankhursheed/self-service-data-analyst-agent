# Conversations and follow-up questions

Brief section 18. Follow-up questions work, and they stay exactly as safe as new ones.

Code: `app/agent/conversations.py` (`ConversationService`), `app/agent/memory.py`
(PostgreSQL checkpointer), `app/db/setup/checkpoints.py` (tables, created by the seed).

## Conversation state

- **Checkpointer:** LangGraph's `AsyncPostgresSaver`, pooled, connecting as the
  application role `app_rw` with `search_path` set to the schema `checkpoints`. The seed
  creates its tables as the owner (`PostgresSaver.setup()`), and `app_rw` gets
  `SELECT, INSERT, UPDATE, DELETE` on them. `analytics_ro` has no access.
- **Serializer:** only the application's own state types can be restored from a checkpoint
  (`app/agent/checkpoint.py`).
- **Thread ID:** `user:<user id>:conversation:<conversation id>`. The service builds a
  thread ID only after checking that the conversation belongs to the requesting user, so
  one user can never load another user's thread. A different user asking with the same
  conversation ID gets `ConversationNotFound` (`NOT_FOUND`, no hint that it exists).
- **App tables:** a conversation is a row in `app.conversations` (owner, title). Every
  question is a row in `app.questions` (correlation ID, conversation, user, text, role,
  region, status), updated when it finishes with the final status, resolved period,
  assumptions and completion time. A clarification reply updates the same row.

## Follow-ups

1. `ConversationService.ask(user, question, conversation_id)` reads the previous final
   state of the thread and passes a short **history** (the last 5 questions: the question,
   its standalone version, status, SQL and period) into a fresh run.
2. The intent prompt (`config/prompts/intent/v2.yaml`) shows that history. For a question
   that only makes sense with an earlier one ("now only for Germany", "show the same by
   month") the model returns `is_follow_up: true` and a full `standalone_question`.
3. N-03 stores it as `interpreted_question` and adds the notice
   *"Interpreted as: Top 5 products by revenue in 2025 for customers in Germany"*, returned
   as `interpreted_as` in the response. Retrieval and SQL generation use the standalone
   question.
4. **Every follow-up runs the full graph again:** intake, guardrails, intent, context,
   generation, validation, the read-only role with the user's own role and region. Nothing
   is skipped and no earlier SQL is executed again; earlier SQL appears only as history
   text for the model, and whatever the model writes is validated like any other query.
5. A new question in the same thread starts from a completely fresh state: every field is
   passed explicitly, and the per-question `steps` list is not carried over. Only the
   history is.

## Starting, listing and opening

| Function | What it does |
| --- | --- |
| `start_conversation(user, title)` | Creates an empty conversation for the user. |
| `ask(user, question)` | Starts a new conversation (title from the question) with no history. |
| `ask(user, question, conversation_id)` | A follow-up in the user's own conversation. |
| `clarify(user, conversation_id, reply)` | Answers the pending clarifying question (N-04). |
| `list_conversations(user)` | The user's conversations, newest first, with question counts. |
| `open_conversation(user, conversation_id)` | The questions of one of the user's conversations. |

## Windows note

psycopg's async driver cannot use Windows' default Proactor event loop. Tests use the
selector loop (`tests/conftest.py`); the API server will do the same when it runs on
Windows. Docker (Linux) is not affected.

## Tests

- `tests/integration/test_conversations_db.py` (real database and checkpointer, scripted
  LLM): "Top 5 products by revenue in 2025" then "now only for Germany" returns exactly the
  rows of an independent owner query (scenario 8); `sales.americas` asking "now only for
  Germany" gets an honest empty result because the database keeps it to the Americas;
  user A's conversation cannot be opened, continued or clarified by user B; a new
  conversation carries no earlier context.
- `tests/unit/test_follow_ups.py`: rewriting and the "Interpreted as" notice, follow-ups
  still blocked by guardrails, thread-ID scoping, fresh state per question.
