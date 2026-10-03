# Product Requirements Document — Advisor Console

## 0) Meta

| | |
| --- | --- |
| **Feature name** | Advisor Console — Career Transition Advisor |
| **Doc owner** | Eskwelabs EIF intern pair |
| **Date / version** | 2026-10-03 · v1.0 revised |
| **Timeline** | 3 weeks |
| **Deployment target** | Backend on Render/Fly (long-lived process); frontend static on Vercel; database on Supabase |
| **Stack as built** | FastAPI + psycopg3 · Supabase Postgres (`advisor` schema) · Google Docs API (read-only) for prompt + grounding · single model via OpenRouter · Vite + React + TypeScript frontend |

This is the revised requirements document. v0.1 was the filled draft. v1.0
locks the specifications that review and the build made final: requirement
priority, the enforcement rules a literal reading left ambiguous, and the
recorded evaluation. How those rules are implemented, and why a simpler reading
would have been wrong, stays in [`ARCHITECTURE.md`](ARCHITECTURE.md).

### Revision record

| Version | Date | Change |
| --- | --- | --- |
| v0.1 | Draft | Filled PRD from the assignment. FR-03 was marked Could. Several enforcement rules were stated as outcomes only. |
| v1.0 | 2026-10-03 | Revised. FR-03 is Must, matching the required set (FR-01–FR-05 and FR-07–FR-09). Caps, document cache, secrecy, retries, and mid-stream persistence are now specified, not only described after the fact. Live eval result recorded. |

---

## 1) Problem, goals & non-goals

### 1.1 Problem statement

Eskwelabs' EIF mentoring runs on third-party Custom GPTs/Gems that cannot be
centrally managed — prompts are hard to iterate, conversations are not logged, and
there is no cost or quality control. This project builds a small, single-advisor
version of that idea: an internally-owned console that brokers a user ↔ LLM
conversation while keeping the prompt externally editable, grounding replies in a
reference doc, capping usage, and logging everything for review.

### 1.2 Primary goals

- Web-based chat for one advisor persona, usable by a handful of test users.
- System prompt out of the client, editable live from a Google Doc, no redeploy.
- Every conversation logged; a user can resume a past session.
- Hard per-user caps on tokens/messages plus basic rate limiting.
- Tone and facts grounded in a short reference doc via keyword retrieval.
- A lightweight admin view of logs, usage, and cost.

### 1.3 Success metrics

| KPI | Target | How it is verified |
| --- | --- | --- |
| Completed turns persisted without loss | ≥ 99% | Every exit path writes a `messages` row, including blocked, errored, redacted, and client-disconnect turns |
| Prompt / grounding edit → live | ≤ cache TTL, zero redeploy | 300s TTL; admin "Re-read docs" forces it immediately for the demo |
| Over-cap requests hard-blocked | 100% | Enforced inside one Postgres transaction behind a per-user advisory lock, so concurrent sends cannot race past the cap |
| System prompt / grounding exposed to client | 0 | Three layers: no response schema can carry it (test-enforced), server-injected confidentiality clause, canary + verbatim egress scan |
| Past conversations resumable | 100% | Conversation id is in the URL; full history re-renders and new turns continue with context |

### 1.4 Non-goals

- Enterprise auth or large allow-lists. A simple email/password session is enough.
- Real vector RAG or embeddings. Lexical keyword retrieval only, by design.
- Multi-advisor or multi-admin support.
- An in-app prompt editor. Prompt and grounding doc are edited only in Google Docs.
- Production-grade uptime or SLA. This is a learning build.

---

## 2) Users & use cases

### 2.1 Personas

**End user (primary).** Signs in, chats with the advisor, revisits and resumes past
conversations. Sees their own remaining daily allowance. Never sees the system
prompt, the grounding doc, or any cost figure.

**Admin (the pair, secondary).** Edits the prompt and grounding doc in Google Docs,
sets caps and limits via environment or per-user overrides, reviews logs and
usage/cost.

### 2.2 Top use cases

1. User signs in, chats, and gets on-persona guidance grounded in the reference doc.
2. User returns later, opens history, and resumes a prior thread with context intact.
3. Admin edits a Google Doc; new behaviour is live within the cache TTL, no redeploy.
4. User hits their daily cap mid-session and is clearly, gracefully blocked.
5. Admin reviews recent conversations, per-user usage, and estimated cost.

### 2.3 Constraints & assumptions

- Three-week build by a pair of interns: favour simple, well-understood tools.
- Google Docs is the control plane — cache with a short TTL to tolerate latency,
  and keep a durable last-good copy so a Docs outage is survivable.
- Secrets live only in environment variables, never in code or the client.

### 2.4 Functional requirements

| ID | Priority | Status | Implementation |
| --- | --- | --- | --- |
| **FR-01** Multi-turn chat with maintained context | Must | Done | `turn.py` assembles system + last `MAX_HISTORY_TURNS` turns + new message. Blocked/errored rows are excluded from model context so a cap notice never becomes conversation. |
| **FR-02** Prompt hidden from users, editable via Google Doc | Must | Done | `docsource/` — `DocumentSource` protocol with Google Docs and local-file providers; 300s TTL cache plus `doc_snapshots` as a durable last-good store. Prompt is injected server-side only and has no response field anywhere. |
| **FR-03** Replies grounded in a reference doc | Must | Done | `grounding.py` — heading-aware chunker, BM25-style scoring with document-frequency weighting, query coverage, and heading focus. Chunk ids used are recorded per turn. Raised from Could in v0.1: the assignment requires it. |
| **FR-04** See and resume past conversations | Must | Done | Sidebar history; `/c/:id` route; `GET /api/conversations/{id}` returns full history. Partial turns from a mid-stream disconnect are persisted so resume is accurate. |
| **FR-05** Per-user caps on tokens/messages | Must | Done | `advisor.reserve_turn()` — message, token, and spend caps checked and reserved atomically. Blocked turns are persisted and logged. Per-user overrides on `users`. |
| **FR-06** Basic rate limiting | Should | Done | Sliding window over `events`, evaluated in the same transaction as the caps. Returns `Retry-After` and a seconds countdown. |
| **FR-07** Every turn logged | Must | Done | `messages` stores content, role, status, prompt/completion tokens, estimated cost, model, latency, and the prompt + grounding revision ids. `events` holds the telemetry stream. |
| **FR-08** Lightweight usage view | Must | Done | `/api/admin/*` and the admin console: activity totals, doc revisions, and four log views (turns, usage, conversations, events). |
| **FR-09** Eval set | Must | Done | 12 cases in `evals/eval_set.yaml` with machine-checkable assertions; `run_eval.py` scores the rubric and writes `EVAL_RESULTS.md`. Offline mode needs no API key. |

### 2.5 Non-functional requirements

| Category | Requirement | Status |
| --- | --- | --- |
| Security | Prompt & grounding text never reach the client | Structural (no such response field, test-enforced), instructional (server-injected clause), and detective (canary + verbatim egress scan, redacts and logs) |
| Reliability | Graceful handling of Doc/provider/DB failures | Full matrix in `ARCHITECTURE.md` §6. Provider and doc failures refund the learner's message allowance. |
| Observability | All §8 events captured | All PRD events plus `doc_revision_changed`, `prompt_leak_blocked`, `prompt_probe_suspected`, `idempotent_replay`, login outcomes |
| Maintainability | Prompt/grounding edits require no redeploy | Doc edit is live within the TTL; admin "Re-read docs" forces it on demand |

---

## 3) Data & knowledge sources

**Grounding doc** — [`content/grounding.md`](../content/grounding.md). Defines the
persona's voice, core principles, Philippine market context, portfolio and résumé
guidance, do's/don'ts, and escalation rules. Chunked on markdown headings and
keyword-matched. No embeddings.

**Prompt doc** — [`content/prompt.md`](../content/prompt.md). Role, method, scope,
behaviour rules, confidentiality, output format.

Both files mirror the Google Docs that serve as the live source when
`DOC_PROVIDER=google_docs`; they are the active source when `DOC_PROVIDER=local`,
which is how the app and the eval harness run without Google credentials.

**Loading rules.** Cache key is `(advisor_id, doc_kind)`; TTL 300s. Every
successful fetch is hashed and upserted into `doc_snapshots`. On fetch failure,
serve the newest snapshot and mark it stale in the admin view. If no snapshot
exists, return a user-facing error and **do not call the LLM** — a model with no
system prompt is worse than an error message.

---

## 4) Prompting & model configuration

| Prompt | Purpose | Owner | Version |
| --- | --- | --- | --- |
| Grounding excerpt | Voice/tone/fact grounding, prepended | Admin | `doc_snapshots.revision_hash` |
| Persona prompt | Role, scope, behaviour rules | Admin | `doc_snapshots.revision_hash` |
| Platform rules | Confidentiality, injection resistance | Code (`prompting.py`) | Versioned with the repo |

Final system message = grounding excerpt + persona prompt + platform rules,
assembled server-side only. Doc revisions are real identifiers rather than a note:
each `messages` row points at the exact prompt and grounding revision that
produced it, so any turn can be traced back to the text responsible.

Model defaults: `openai/gpt-4o-mini`, temperature 0.4, `max_tokens` 900, 12 turns
of history. All configurable per advisor in the `advisors` table.

---

## 5) Flow

1. User signs in → opens the advisor or resumes a past conversation.
2. User sends a message → idempotency replay check → cap and rate check in one
   atomic step (block + log if exceeded).
3. Prompt and grounding loaded from cache, or fetched on miss; relevant grounding
   chunks selected for this specific message.
4. Assembled context sent to the model; reply streamed over SSE.
5. Reply scanned for leakage, turn persisted with tokens/cost/status, reservation
   settled against real usage → visible in the admin view.

---

## 6) Sample inputs & outputs

**Input.** "I'm falling behind on my project — how should I prioritize this week?"

**Expected output.** Advisory, on-persona guidance reflecting the grounding doc's
diagnostic-first framing: name the binding constraint, give 2–4 sequenced actions
for this week, end with a checkable signal. No prompt or grounding text leaked, no
promised outcome.

### Edge cases

| Case | Behaviour | Persisted status |
| --- | --- | --- |
| Cap exceeded | Hard block, message naming the reset time, both sides logged | `blocked_cap` |
| Rate limit exceeded | Block with retry guidance and a countdown | `blocked_rate` |
| Doc unreachable, snapshot exists | Serve last-good, flag stale to admin | `ok` |
| Doc unreachable, no snapshot | User-facing error, no LLM call, allowance refunded | `doc_error` |
| User asks to see the system prompt | Advisor declines; server never returns it; a compliant reply would be redacted and logged | `ok` or `redacted` |
| Provider error/timeout | 3 attempts with backoff, then graceful error, allowance refunded | `provider_error` |
| Client disconnects mid-stream | Partial reply persisted so resume is accurate | `truncated` |

---

## 7) Evaluation

### 7.1 Rubric

| Criterion | Weight | Scored by |
| --- | --- | --- |
| Task success / relevance | 0.20 | Automated |
| Grounding fidelity | 0.20 | Automated |
| Guardrail enforcement | 0.20 | Automated |
| Robustness | 0.15 | Automated |
| Architecture & code quality | 0.15 | Human |
| Eval rigor & writeup | 0.10 | Human |

### 7.2 Pass criteria

| Criterion | Status |
| --- | --- |
| All Must FRs working end to end | FR-01 through FR-05 and FR-07 through FR-09 are Must and done. FR-06 (Should) is also done. |
| Prompt/grounding secrecy verified adversarially | Live run 2026-10-03: three adversarial cases passed; three planted leaks caught; the benign reply was not flagged |
| Cap enforcement verified adversarially | Same run: `GUARD-01` blocked as `rate_limited`, `GUARD-02` blocked as `message_cap` |
| Prompt/grounding edit → live within TTL | 300s cache; admin "Re-read docs" forces a fetch with no redeploy |
| Past conversations reopen with full history | Yes, via `/c/:id` |
| Eval set run with documented results | [`EVAL_RESULTS.md`](EVAL_RESULTS.md): 12 pass, 0 fail. Automated rubric 3.75 / 3.75. Reflection in [`EVAL.md`](EVAL.md) |

---

## 8) Telemetry & schema

**Events.** `message_sent`, `llm_call_completed`, `request_blocked`,
`prompt_cache_hit`, `prompt_cache_miss`, `doc_fetch_error`, `provider_error` — all
as specified — plus `doc_revision_changed`, `prompt_leak_blocked`,
`prompt_probe_suspected`, `idempotent_replay`, `login_succeeded`, `login_failed`,
`admin_access_denied`.

**Tables.** The three minimal tables from the PRD, plus five the requirements
imply:

| Table | PRD | Notes |
| --- | --- | --- |
| `conversations` | yes | Plus rollup counters maintained by trigger |
| `messages` | yes | Plus `turn_id`, `client_request_id`, prompt/grounding snapshot FKs, `grounding_chunk_ids`, `latency_ms` |
| `usage_counters` | yes | Plus `tokens_reserved`; `usage_date` is the day in `APP_TIMEZONE` |
| `users`, `sessions` | implied by auth | scrypt hashing; per-user cap overrides |
| `advisors` | implied | Model/temperature/doc refs, keyed so nothing assumes a singleton |
| `doc_snapshots` | implied by "last-good cache" | Durable last-good + revision registry |
| `events` | implied by §8 | Append-only, one shape, `jsonb` payload |

Row-level security is enabled on all eight tables with zero policies; the backend
connects with the service role.

---

## 9) Finalized specifications

These were outcomes in v0.1. They are requirements now.

| Rule | Specification |
| --- | --- |
| Cap check | One Postgres transaction per send, behind a per-user advisory lock. Reserve estimated tokens before the model call; settle to real usage after; release the reservation on a document, provider, or client failure. A check-then-call is not sufficient. |
| Rate limit | Same transaction as the caps. Sliding window of 6 sends per 60 seconds, counted from `message_sent` events. Checked before the daily cap. |
| Cap day | `usage_date` is the calendar date in `Asia/Manila`, not UTC. |
| Defaults | 40 messages, 60,000 tokens, and $0.50 estimated spend per user per day. Per-user columns override these. 0 means unlimited. |
| Document cache | 300 second TTL in process, plus a durable `doc_snapshots` row for every successful fetch. A failed fetch serves the newest snapshot and marks it stale. No snapshot means a user-facing error and no model call. |
| Prompt secrecy | No API response field can carry the prompt or grounding text. A confidentiality clause is appended in code, not only in the Doc. Every completion is scanned for a canary and for a 12-word overlap; a hit is redacted, stored as `redacted`, and logged. |
| Retries | `client_request_id` replays the stored turn. A repeated send does not spend a second message. |
| Disconnect | A cancelled stream is stored as `truncated` with the text generated so far, and usage is settled. |
| Retrieval | Lexical only. The score threshold is a quality control. It is not the secrecy control. |
| Idempotent history | Blocked and errored rows are logged and are excluded from the next model context. |

## 10) Open questions & risks — resolved

| Item | Resolution |
| --- | --- |
| Auth method | Email/password with an opaque httpOnly session cookie, scrypt hashing, server-side revocation. No SSO. |
| Retrieval quality | Lexical only, as scoped. Measured, not assumed: `scripts/tune_threshold.py` shows legitimate questions and off-domain prompts are separable but injection attempts and real questions are **not**. Paraphrase without shared vocabulary is missed — documented in `ARCHITECTURE.md` §3 and §9. |
| Cap/budget values | 40 messages, 60,000 tokens, $0.50/day, 6 requests/minute. Rationale in `ARCHITECTURE.md` §5; the two primary caps are sized to bind at roughly the same point so neither is decorative. |
| Time risk | Scope locked to the Must FRs, including FR-03. FR-06 was completed as well. Deferred: multi-advisor, embeddings, in-app prompt editing, cost reconciliation against provider billing. |
