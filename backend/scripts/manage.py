"""Operational CLI.

    python -m scripts.manage migrate
    python -m scripts.manage create-user alvin@example.com "Alvin" --role admin
    python -m scripts.manage list-users
    python -m scripts.manage check-docs
    python -m scripts.manage verify-guardrails
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import close_pool, connection, fetch_all  # noqa: E402
from app.runtime import run as run_async  # noqa: E402
from app.docsource import GROUNDING, PROMPT, DocumentStore  # noqa: E402
from app.security import hash_password  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
MIGRATIONS = BACKEND / "migrations"
GUARDRAIL_SQL = BACKEND / "tests" / "sql" / "verify_guardrails.sql"

# Bootstrap table: the runner has to create this before it can read it, so it
# lives here rather than in migrations/. RLS matches the other tables — on, with
# no policies, so only the service role sees it.
_LEDGER = """
create table if not exists advisor.schema_migrations (
    filename   text primary key,
    sha256     text not null,
    applied_at timestamptz not null default now()
);
alter table advisor.schema_migrations enable row level security;
"""


async def migrate() -> None:
    """Apply any migration not yet recorded in the ledger.

    0001_init.sql uses bare `create table`, so re-running it against a
    provisioned database fails. A ledger makes this command safe to run
    repeatedly, which matters because it is the one command someone will reach
    for when they are unsure what state the database is in.
    """
    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        print("no migrations found")
        return

    async with connection() as conn:
        await conn.execute("create schema if not exists advisor")
        await conn.execute(_LEDGER)
        cur = await conn.execute("select filename, sha256 from advisor.schema_migrations")
        applied = {row["filename"]: row["sha256"] for row in await cur.fetchall()}

    pending = 0
    for path in files:
        body = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if path.name in applied:
            if applied[path.name] != digest:
                # Not fatal: a comment edit or a line-ending change is harmless.
                # Still worth saying out loud, because the alternative is a
                # migration whose recorded history no longer matches the file.
                print(f"  {path.name:<40} already applied (file has changed since)")
            else:
                print(f"  {path.name:<40} already applied")
            continue

        pending += 1
        print(f"  {path.name:<40} applying ...", end=" ", flush=True)
        # One transaction per migration: Postgres DDL is transactional, so a
        # failure leaves nothing half-created.
        async with connection() as conn:
            async with conn.transaction():
                # Passed without parameters on purpose: psycopg only falls back to
                # the simple query protocol when there are none, and that is the
                # only protocol that accepts several statements in one string.
                # Adding a parameter here, or enabling pipeline mode on the pool,
                # would break every multi-statement migration file.
                await conn.execute(body)
                await conn.execute(
                    "insert into advisor.schema_migrations (filename, sha256) values (%s, %s)",
                    (path.name, digest),
                )
        print("ok")

    print(f"{pending} applied, {len(files) - pending} already present")

    await _verify_schema()


_REQUIRED_TABLES = (
    "users",
    "sessions",
    "advisors",
    "doc_snapshots",
    "conversations",
    "messages",
    "usage_counters",
    "events",
)
_REQUIRED_FUNCTIONS = ("touch_conversation", "reserve_turn", "settle_turn", "release_turn")


async def _verify_schema() -> None:
    """Confirm what actually landed.

    "migrate exited 0" and "the schema is correct" are different claims, and on a
    fresh project the second is the one that matters. Checked by name rather than
    by count so that adding a migration later does not break this.
    """
    async with connection() as conn:
        cur = await conn.execute(
            "select table_name from information_schema.tables"
            " where table_schema = 'advisor' and table_type = 'BASE TABLE'"
        )
        tables = {row["table_name"] for row in await cur.fetchall()}
        cur = await conn.execute(
            "select routine_name from information_schema.routines where routine_schema = 'advisor'"
        )
        functions = {row["routine_name"] for row in await cur.fetchall()}
        cur = await conn.execute("select count(*) as n from advisor.advisors")
        advisors = (await cur.fetchone())["n"]

    missing = [f"table advisor.{t}" for t in _REQUIRED_TABLES if t not in tables]
    missing += [f"function advisor.{f}" for f in _REQUIRED_FUNCTIONS if f not in functions]
    if advisors < 1:
        missing.append("seed row in advisor.advisors")

    if missing:
        raise SystemExit(
            "schema is incomplete:\n"
            + "\n".join(f"  missing {m}" for m in missing)
            + "\nInspect advisor.schema_migrations, or apply migrations/*.sql with psql."
        )

    print(
        f"schema verified: {len(tables)} tables, {len(functions)} functions, "
        f"{advisors} advisor row(s)"
    )
    print("next: python -m scripts.manage verify-guardrails")


async def verify_guardrails() -> None:
    """Run the SQL guardrail suite without needing psql installed.

    The caps and the rate limiter are enforced by PL/pgSQL, so no Python test can
    reach them. This is the only check that proves they hold.
    """
    body = GUARDRAIL_SQL.read_text(encoding="utf-8")
    rows: list[dict] = []
    async with connection() as conn:
        cur = await conn.execute(body)
        # The file is create-function / select / drop-function, so the rows we
        # want sit in the middle result set.
        while True:
            names = [d.name for d in cur.description] if cur.description else []
            if names[:2] == ["step", "ok"]:
                rows = await cur.fetchall()
            if not cur.nextset():
                break

    if not rows:
        raise SystemExit("no assertions returned — did verify_guardrails.sql change shape?")

    failed = 0
    for row in rows:
        mark = "PASS" if row["ok"] else "FAIL"
        if not row["ok"]:
            failed += 1
        print(f"  {mark}  {row['step']:<58} {row['detail']}")

    print(f"\n{len(rows) - failed}/{len(rows)} assertions passed")
    if failed:
        raise SystemExit(f"{failed} guardrail assertion(s) failed — this is a real defect")


async def create_user(email: str, name: str, role: str, password: str | None) -> None:
    password = password or getpass.getpass("Password: ")
    if len(password) < 8:
        raise SystemExit("password must be at least 8 characters")
    async with connection() as conn:
        cur = await conn.execute(
            """
            insert into advisor.users (email, display_name, password_hash, role)
            values (%s, %s, %s, %s)
            on conflict (lower(email)) do update
               set display_name = excluded.display_name,
                   password_hash = excluded.password_hash,
                   role = excluded.role
            returning id, email, role
            """,
            (email.strip().lower(), name, hash_password(password), role),
        )
        row = await cur.fetchone()
    print(f"user {row['email']} ({row['role']}) -> {row['id']}")


async def list_users() -> None:
    rows = await fetch_all(
        "select email, display_name, role, created_at from advisor.users order by created_at"
    )
    if not rows:
        print("no users yet")
        return
    for row in rows:
        print(f"{row['role']:<6} {row['email']:<34} {row['display_name']}")


async def check_docs() -> None:
    """Verify the control plane end to end without touching the model."""
    settings = get_settings()
    store = DocumentStore(settings)
    advisor_rows = await fetch_all(
        "select * from advisor.advisors where id = %s", (settings.advisor_id,)
    )
    if not advisor_rows:
        raise SystemExit(f"advisor '{settings.advisor_id}' not found — run migrate first")
    advisor = advisor_rows[0]

    print(f"provider: {store.source_name}  ttl: {settings.doc_cache_ttl_seconds}s")
    for kind in (PROMPT, GROUNDING):
        revision = await store.get(advisor["id"], kind, advisor, required=(kind == PROMPT))
        if revision is None:
            print(f"  {kind:<9} not configured")
            continue
        flag = " [STALE last-good]" if revision.stale else ""
        print(
            f"  {kind:<9} {revision.short_hash}  {revision.char_count if hasattr(revision, 'char_count') else len(revision.body):>6} chars"
            f"  via {revision.source}{flag}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="manage")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate")
    sub.add_parser("list-users")
    sub.add_parser("check-docs")
    sub.add_parser("verify-guardrails")

    create = sub.add_parser("create-user")
    create.add_argument("email")
    create.add_argument("name")
    create.add_argument("--role", default="user", choices=["user", "admin"])
    create.add_argument("--password", default=None)

    args = parser.parse_args()

    async def run() -> None:
        # Every command here needs the database. A missing or malformed
        # DATABASE_URL is the single most likely setup mistake, so it gets a
        # sentence rather than a traceback.
        if not get_settings().database_url:
            raise SystemExit(
                "DATABASE_URL is not set.\n"
                "  - Run this from the backend/ directory; .env is read relative to the cwd.\n"
                "  - Copy .env.example to .env and fill in DATABASE_URL.\n"
                "  - Supabase > Project Settings > Database > Connection string."
            )
        try:
            if args.command == "migrate":
                await migrate()
            elif args.command == "create-user":
                await create_user(args.email, args.name, args.role, args.password)
            elif args.command == "list-users":
                await list_users()
            elif args.command == "check-docs":
                await check_docs()
            elif args.command == "verify-guardrails":
                await verify_guardrails()
        finally:
            await close_pool()

    run_async(run())


if __name__ == "__main__":
    main()
