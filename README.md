# Advisor Console

An internally owned, lightweight AI advisor console for Eskwelabs' EIF mentoring.

The Advisor Console provides a web-based chat experience for a single advisor persona while giving the team control over the advisor's **system prompt, grounding knowledge, usage limits, conversation history, logging, and evaluation**.

Instead of relying on third-party Custom GPTs or Gems, the system brokers the user–LLM interaction through a backend that keeps prompts and sensitive configuration server-side.

---

## Overview

The Advisor Console is designed as a small, manageable MVP that allows a team to:

- Chat with a single AI advisor persona
- Maintain multi-turn conversation context
- Resume previous conversations
- Edit the advisor's system prompt through Google Docs without redeploying
- Ground responses using a short Google Docs reference document
- Enforce per-user message and token limits
- Apply basic rate limiting
- Log conversations, usage, token counts, estimated costs, and request status
- Monitor usage through a lightweight admin view
- Run an evaluation set to check relevance, grounding, guardrails, and robustness

The project intentionally favors simple and understandable architecture over production-scale infrastructure.

---

## Problem

Eskwelabs' EIF mentoring currently relies on third-party Custom GPTs/Gems that are difficult to centrally manage.

This creates several limitations:

- Prompts are difficult to iterate and manage centrally
- Conversations are not controlled through an internally owned system
- Usage and cost are difficult to monitor
- There is limited visibility into advisor quality
- Guardrails such as usage caps and rate limits are difficult to enforce consistently

The Advisor Console addresses these issues with a small internally owned application.

---

## Goals

The MVP aims to:

1. Provide a working web chat for one advisor persona.
2. Keep the system prompt completely server-side.
3. Allow prompt and grounding-document changes through Google Docs without redeployment.
4. Persist conversations and allow users to resume them.
5. Enforce per-user message/token caps.
6. Apply basic request rate limiting.
7. Log every completed, blocked, and failed request.
8. Provide a lightweight admin usage and cost view.
9. Evaluate the advisor against a small set of normal and adversarial prompts.

---

## Core Features

### User

- Simple authentication/session
- Multi-turn advisor chat
- Conversation history
- Resume previous conversations
- Clear cap/rate-limit feedback

### Advisor

- Single configurable advisor persona
- Server-side system prompt
- Google Docs-based prompt management
- Google Docs-based grounding knowledge
- Keyword-based grounding retrieval
- LLM responses through OpenRouter

### Admin

- Usage monitoring
- Conversation/log review
- Estimated token usage
- Estimated cost
- Per-user limits
- Prompt and grounding management through Google Docs
- Evaluation set and results
