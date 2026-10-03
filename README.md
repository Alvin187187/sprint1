# Advisor Console — Career Transition Advisor

An internally-owned console that brokers a learner ↔ LLM conversation while
keeping the system prompt externally editable, grounding replies in a reference
doc, capping usage per user, and logging every turn for review.

Built against the Advisor Console PRD. Replaces third-party Custom GPTs/Gems for
Eskwelabs EIF mentoring with something the team can actually manage.

- [`docs/PRD.md`](docs/PRD.md) — revised requirements (v1.0), with the finalized specifications
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how it works and where it
  deliberately departs from the PRD
- [`docs/EVAL.md`](docs/EVAL.md) — evaluation methodology and reflection
- [`docs/EVAL_RESULTS.md`](docs/EVAL_RESULTS.md) — generated results

---

## Stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI (Python 3.12+), async psycopg3 |
| Frontend | Vite + React + TypeScript + Tailwind v4 |
| Database | Supabase Postgres, dedicated `advisor` schema |
| Model | Any single model via OpenRouter (default `openai/gpt-4o-mini`) |
| Prompt control plane | Google Docs (read-only) with a local-file provider for dev |

---

## Layout

```
backend/
  app/
    config.py          settings, all from env
    db.py              psycopg3 async pool
    security.py        scrypt password hashing, session tokens
    docsource/         prompt + grounding control plane
      base.py          DocumentSource protocol, DocumentRevision
      local.py         local-file provider (dev / eval)
      google_docs.py   Docs REST + service-account auth
      store.py         TTL cache + durable last-good snapshots
    grounding.py       heading chunker + BM25-ish keyword retrieval
    guardrails.py      reserve → settle / release around the SQL critical section
    prompting.py       system-message assembly, canary, leak scan, probe heuristic
    pricing.py         token estimation and cost attribution
    llm.py             OpenRouter client, SSE streaming, retries
    turn.py            turn orchestration
    repository.py      SQL data access
    routers/           auth, conversations, chat, admin
  migrations/0001_init.sql
  scripts/
    manage.py          migrate, create-user, list-users, check-docs
    inspect_chunks.py  chunk inventory + retrieval trace
    diagnose_query.py  per-term idf and full ranking for a query
    tune_threshold.py  threshold separability measurement
  evals/
    eval_set.yaml      12 cases incl. adversarial and guardrail
    run_eval.py        harness, offline and live modes
  tests/               40 tests, no DB or API key needed
content/
  prompt.md            persona prompt (mirrors the Google Doc)
  grounding.md         reference/brand doc (chunked and keyword-matched)
frontend/src/
  lib/                 api client incl. SSE reader, types, formatters
  components/          ui primitives, icons, Thread, Sidebar, UsageMeter
  pages/               LoginPage, ChatPage, AdminPage
design-system/advisor-console/MASTER.md
```

---

## Setup

Run every backend command from inside `backend/`. `app/config.py` loads `.env`
relative to the working directory, so running from the repo root silently gives
you an unconfigured app rather than an error.

### 1. Secrets

There is exactly one secrets file, `backend/.env`. It is gitignored. The frontend
needs none — Vite proxies `/api` to port 8000, so there is no API base URL to
configure and no key ever reaches the browser.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt
copy .env.example .env           # cp on macOS/Linux
```

Then set three values in `.env`. Everything else already has a working default.

| Variable | Where it comes from |
| --- | --- |
| `DATABASE_URL` | Supabase → **Project Settings → Database → Connection string**. Use the **session pooler** (port 5432) for a long-lived server. |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys). Needs a few dollars of credit; `openai/gpt-4o-mini` costs well under a cent per turn. |
| `ADMIN_EMAILS` | Your own email, comma-separated. Grants admin in addition to `role='admin'` in the database. |

The shape of the DSN, with `<ref>` being your project ref and `<region>` matching
the project's region (both are in the connection string Supabase shows you):

```env
DATABASE_URL=postgresql://postgres.<ref>:YOUR_DB_PASSWORD@aws-1-<region>.pooler.supabase.com:5432/postgres
OPENROUTER_API_KEY=sk-or-v1-...
ADMIN_EMAILS=you@example.com
```

If your database password contains `@`, `:`, `/`, `#` or `?`, percent-encode it —
otherwise it breaks the DSN and you get an authentication error that looks like a
wrong password. Resetting it to something alphanumeric under
**Database → Reset database password** is the faster path.

### 2. Database

```bash
python -m scripts.manage migrate
```

That is all. It creates the `advisor` schema, eight tables, four functions, the
rollup trigger, the usage view, RLS on everything, and the seeded advisor row.

The command is ledger-backed (`advisor.schema_migrations`), so it is safe to run
repeatedly: already-applied files are reported and skipped. That also makes it the
cheapest check that `DATABASE_URL` is correct.

**Nothing in the app is tied to a particular Supabase project or organization.**
The only coupling is `DATABASE_URL`. To move to a different project — a different
org, a teammate's account, a throwaway for testing — create an empty project, put
its connection string in `.env`, and run `migrate`. There is no project ref
anywhere in the code, and no Supabase client library: the backend talks to Postgres
directly over psycopg, so the API keys and the dashboard are irrelevant at runtime.

### 3. Accounts, then run it

```bash
python -m scripts.manage create-user you@example.com "Your Name" --role admin
python -m scripts.manage create-user learner@example.com "Test Learner"
python -m scripts.manage list-users
uvicorn app.main:app --reload --port 8000 --loop app.runtime:selector_loop_factory
```

`create-user` prompts for the password rather than taking it as an argument, so it
does not land in your shell history.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to port 8000
```

---

## Switching the prompt to Google Docs

The app ships with `DOC_PROVIDER=local`, reading `content/prompt.md` and
`content/grounding.md` so everything runs without Google credentials. To move the
control plane into Docs:

1. Create a Google Cloud service account and download its JSON key. Enable the
   Google Docs API on the project.
2. Create two Docs — one whose body is the system prompt, one the reference doc.
   Paste `content/prompt.md` and `content/grounding.md` as a starting point.
   **Keep the markdown headings in the reference doc** — the chunker splits on
   them and they carry weight in retrieval scoring.
3. Share both Docs with the service account's email as **Viewer**.
4. Set in `.env`:

```env
DOC_PROVIDER=google_docs
GOOGLE_SERVICE_ACCOUNT_JSON=./service-account.json
PROMPT_DOC_ID=<id from the Doc URL>
GROUNDING_DOC_ID=<id from the Doc URL>
```

5. `python -m scripts.manage check-docs` to confirm, then restart.

Editing either Doc goes live within `DOC_CACHE_TTL_SECONDS` (default 300) with no
redeploy. The admin console's **Re-read docs** button bypasses the TTL, which is
what you want during a demo rather than waiting out five minutes.

---

## Verifying it

### Needs no credentials

```bash
cd backend
python -m pytest -q                      # 40 tests
python -m evals.run_eval --offline       # retrieval + secrecy, no provider calls
python scripts/inspect_chunks.py         # which section each question retrieves
python scripts/tune_threshold.py         # threshold separability
```

```bash
cd frontend
npm run build                            # tsc -b gates the build, so this type-checks too
```

### Needs `DATABASE_URL` only

```bash
cd backend
python -m scripts.manage check-docs          # prompt + grounding load, with revision hashes
python -m scripts.manage verify-guardrails   # 19 assertions against the real database
```

`verify-guardrails` is the important one. The caps and the rate limiter are
enforced by PL/pgSQL functions, so no Python test can reach them — this drives each
cap to a block on three throwaway accounts, checks settle and release, and deletes
its own rows afterwards. It is the only check that proves the guardrails hold, and
it already caught a bug that would have broken the first message anyone sent (see
`docs/ARCHITECTURE.md` §8). It needs no `psql`; it runs through the app's own pool.

### Needs `DATABASE_URL` + `OPENROUTER_API_KEY`

```bash
python -m evals.run_eval --live learner@example.com   # full pipeline, real model
```

This is the only command that spends money — 12 prompts against
`openai/gpt-4o-mini`, a few cents total. It writes `docs/EVAL_RESULTS.md` and turns
the two `GUARD-*` cases from SKIP into real assertions, because they need an actual
cap to collide with.

### Current status

| Check | Result |
| --- | --- |
| `pytest` | 40/40 |
| `manage verify-guardrails` | 19/19 against the live database |
| `run_eval --offline` | 12/12 (2 report SKIP — they need `--live`) |
| `npm run build` | clean, no type errors |
| Supabase security linter | 0 warnings; 1 INFO (intentional deny-all RLS) |
| `run_eval --live` | 12/12 on 2026-10-03. Automated rubric 3.75 / 3.75. See `docs/EVAL_RESULTS.md` |

### End to end by hand

1. `uvicorn app.main:app --reload --port 8000 --loop app.runtime:selector_loop_factory` in `backend/`, `npm run dev` in
   `frontend/`, then open http://localhost:5173.
2. `GET http://localhost:8000/api/health` — reports database and provider-key
   status. It deliberately does not fetch the Docs, so probing it cannot burn
   Docs API quota.
3. Log in as `learner@example.com` and ask *"I have 10 hours a week, what should I
   prioritise?"* The reply should stream token by token and the usage meter should
   drop by one.
4. To see a cap actually fire without sending 40 messages, set
   `DEFAULT_DAILY_MESSAGE_CAP=2` in `.env` and restart the backend. The third send
   returns HTTP 429 and the composer shows the block reason rather than a generic
   error. Put the value back afterwards.
5. Log in as your admin account and open **/admin** — the turn log shows both
   learners' messages with token counts, cost, and the doc revision hash each turn
   was grounded against.

### Checking prompt secrecy by hand

`tests/test_api_secrecy.py` enforces this continuously, but to confirm it the way
the PRD describes: open DevTools → Network, send a message, and inspect the SSE
stream and every JSON response. The system prompt, the grounding excerpt, and the
canary marker appear in none of them. Then ask the advisor to print its
instructions — it declines, and if the model ever did comply the response is
redacted server-side and logged as `prompt_leak_blocked` in the admin event log.

---

## Admin console

Visible to users with `role='admin'` or an email in `ADMIN_EMAILS`.

- **Activity** — users, conversations, messages, tokens, estimated spend, blocked
  and errored counts, active model, doc provider, cache TTL, current caps.
- **Prompt & grounding control plane** — the live revision hash of each document,
  its size, cache expiry, and whether it is a stale last-good copy. Revision
  hashes only; document bodies are never served to a client.
- **Logs** — four views: Turns (with token counts, cost, latency, prompt revision,
  and which grounding chunks were injected), Usage (per user per day against
  caps), Conversations, and Events (the full telemetry stream).

---

## Operational notes

- Secrets live only in `.env`. Nothing is committed; nothing reaches the client.
- Caps reset at midnight `APP_TIMEZONE` (`Asia/Manila`), not UTC.
- Row-level security is enabled on all eight tables with no policies — the backend
  uses the service role, so a leaked publishable key reads nothing.
- Verify `PRICES` in `app/pricing.py` against current OpenRouter pricing before
  relying on the cost column.
- `/api/health` reports database and provider-key status. It deliberately does not
  fetch the Docs, so probing it cannot exhaust Docs API quota.
