"""Disposable PostgreSQL integration tests for rate-limit RPC migrations 0011/0012.

Only connects to an explicitly local PostgreSQL host. Never use this test with
production Supabase or a database containing real user data.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "supabase" / "migrations"
DSN = os.environ.get("PWA_RPC_TEST_DATABASE_URL", "")
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validated_dsn() -> str:
    if not DSN:
        pytest.skip("PWA_RPC_TEST_DATABASE_URL is not configured")
    parsed = urlparse(DSN)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in ALLOWED_HOSTS:
        pytest.fail("Refusing non-local database target; use the disposable CI PostgreSQL service")
    return DSN


@pytest.fixture(scope="session")
def dsn() -> str:
    return _validated_dsn()


@pytest.fixture(scope="session", autouse=True)
def disposable_schema(dsn: str):
    # This suite is destructive by design and is only allowed on its isolated,
    # ephemeral CI database. The host allowlist above is an additional guard.
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS auth")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth.users (
                id uuid PRIMARY KEY
            )
        """)
        for role in ("anon", "authenticated", "service_role"):
            conn.execute(
                sql.SQL("DO $$ BEGIN CREATE ROLE {} NOLOGIN; "
                        "EXCEPTION WHEN duplicate_object THEN NULL; END $$").format(
                    sql.Identifier(role)
                )
            )
        conn.execute("GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role")
        conn.execute("GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role")
        conn.execute("GRANT SELECT ON auth.users TO anon, authenticated, service_role")
        for filename in (
            "0011_atomic_message_rate_limit.sql",
            "0012_atomic_ai_rate_limit.sql",
        ):
            conn.execute((MIGRATIONS / filename).read_text(encoding="utf-8"))
    yield
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP FUNCTION IF EXISTS public.consume_ai_rate_limit(uuid, text, integer, integer)")
        conn.execute("DROP FUNCTION IF EXISTS public.consume_message_rate_limit(uuid, integer, integer)")
        conn.execute("DROP TABLE IF EXISTS public.ai_rate_limits")
        conn.execute("DROP TABLE IF EXISTS public.message_rate_limits")
        conn.execute("DROP TABLE IF EXISTS auth.users")
        conn.execute("DROP SCHEMA IF EXISTS auth")


def _new_user(dsn: str):
    user_id = uuid4()
    with psycopg.connect(dsn) as conn:
        conn.execute("INSERT INTO auth.users(id) VALUES (%s)", (user_id,))
    return user_id


def _call(dsn: str, statement: str, params: tuple) -> bool:
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE service_role")
        return conn.execute(statement, params).fetchone()[0]


def test_message_limit_is_exact_and_rejects_invalid_values(dsn):
    user_id = _new_user(dsn)
    stmt = "SELECT public.consume_message_rate_limit(%s, %s, %s)"
    assert [_call(dsn, stmt, (user_id, 3, 60)) for _ in range(4)] == [True, True, True, False]
    with pytest.raises(psycopg.Error):
        _call(dsn, stmt, (user_id, 0, 60))


def test_ai_endpoints_have_independent_counters(dsn):
    user_id = _new_user(dsn)
    stmt = "SELECT public.consume_ai_rate_limit(%s, %s, %s, %s)"
    assert _call(dsn, stmt, (user_id, "chat", 1, 60)) is True
    assert _call(dsn, stmt, (user_id, "chat", 1, 60)) is False
    assert _call(dsn, stmt, (user_id, "prompts", 1, 60)) is True


@pytest.mark.parametrize(
    ("function_sql", "params", "limit_table", "key_columns", "key_values"),
    [
        (
            "SELECT public.consume_message_rate_limit(%s, %s, %s)",
            lambda uid: (uid, 5, 60),
            "public.message_rate_limits",
            "user_id",
            lambda uid: (uid,),
        ),
        (
            "SELECT public.consume_ai_rate_limit(%s, %s, %s, %s)",
            lambda uid: (uid, "chat", 5, 60),
            "public.ai_rate_limits",
            "user_id, endpoint",
            lambda uid: (uid, "chat"),
        ),
    ],
)
def test_concurrent_calls_never_exceed_limit(
    dsn, function_sql, params, limit_table, key_columns, key_values
):
    user_id = _new_user(dsn)
    workers = 16
    barrier = Barrier(workers)

    def invoke(_):
        barrier.wait(timeout=10)
        return _call(dsn, function_sql, params(user_id))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(invoke, range(workers)))
    assert sum(results) == 5
    where = " AND ".join(
        f"{column.strip()} = %s" for column in key_columns.split(",")
    )
    with psycopg.connect(dsn) as conn:
        count = conn.execute(
            f"SELECT request_count FROM {limit_table} WHERE {where}",
            key_values(user_id),
        ).fetchone()[0]
    assert count == 5


def test_fixed_window_resets_counter(dsn):
    user_id = _new_user(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            """INSERT INTO public.message_rate_limits(user_id, window_start, request_count)
               VALUES (%s, to_timestamp(0), 999)""",
            (user_id,),
        )
    assert _call(
        dsn,
        "SELECT public.consume_message_rate_limit(%s, %s, %s)",
        (user_id, 1, 60),
    ) is True


def test_client_roles_cannot_execute_or_access_rate_limit_tables(dsn):
    with psycopg.connect(dsn) as conn:
        for role, function in (
            ("anon", "public.consume_message_rate_limit(uuid,integer,integer)"),
            ("authenticated", "public.consume_ai_rate_limit(uuid,text,integer,integer)"),
        ):
            assert conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                (role, function),
            ).fetchone()[0] is False
        for role in ("anon", "authenticated"):
            assert conn.execute(
                "SELECT has_table_privilege(%s, 'public.message_rate_limits', 'SELECT')",
                (role,),
            ).fetchone()[0] is False
            assert conn.execute(
                "SELECT has_table_privilege(%s, 'public.ai_rate_limits', 'SELECT')",
                (role,),
            ).fetchone()[0] is False
        assert conn.execute(
            "SELECT has_function_privilege('service_role', "
            "'public.consume_message_rate_limit(uuid,integer,integer)', 'EXECUTE')"
        ).fetchone()[0] is True
        assert conn.execute(
            "SELECT has_function_privilege('service_role', "
            "'public.consume_ai_rate_limit(uuid,text,integer,integer)', 'EXECUTE')"
        ).fetchone()[0] is True
