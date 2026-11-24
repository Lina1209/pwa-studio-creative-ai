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

import pytest

psycopg = pytest.importorskip("psycopg", reason="PostgreSQL integration dependency is installed only in the disposable DB workflow")
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
            "0013_unified_credit_wallet.sql",
            "0015_credit_provider_outcome_resolution.sql",
        ):
            conn.execute((MIGRATIONS / filename).read_text(encoding="utf-8"))
    yield
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP FUNCTION IF EXISTS public.resolve_credit_reservation_provider_outcome(uuid, uuid, text, text, bigint)")
        conn.execute("DROP FUNCTION IF EXISTS public.mark_credit_reservation_reconciliation_required(uuid, uuid)")
        conn.execute("DROP FUNCTION IF EXISTS public.release_user_credit_reservation(uuid, uuid)")
        conn.execute("DROP FUNCTION IF EXISTS public.settle_user_credit_reservation(uuid, uuid, bigint)")
        conn.execute("DROP FUNCTION IF EXISTS public.reserve_user_credits(uuid, text, text, integer, bigint)")
        conn.execute("DROP FUNCTION IF EXISTS public.grant_user_credits(uuid, bigint, text, text)")
        conn.execute("DROP TABLE IF EXISTS public.credit_ledger")
        conn.execute("DROP TABLE IF EXISTS public.credit_reservations")
        conn.execute("DROP TABLE IF EXISTS public.credit_wallets")
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



def _wallet_call(dsn: str, statement: str, params: tuple):
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE service_role")
        return conn.execute(statement, params).fetchone()[0]


def _grant(dsn: str, user_id, amount: int, reference: str = "seed-credits"):
    return _wallet_call(
        dsn,
        "SELECT public.grant_user_credits(%s, %s, %s, %s)",
        (user_id, amount, "test", reference),
    )


def _reserve(dsn: str, user_id, key: str, amount: int):
    return _wallet_call(
        dsn,
        "SELECT public.reserve_user_credits(%s, %s, %s, %s, %s)",
        (user_id, key, "image.generate", 1, amount),
    )


def _wallet_row(dsn: str, user_id):
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "SELECT available_credits, reserved_credits FROM public.credit_wallets WHERE user_id = %s",
            (user_id,),
        ).fetchone()


def test_credit_grant_is_idempotent_and_rejects_reused_reference_with_different_amount(dsn):
    user_id = _new_user(dsn)
    first = _grant(dsn, user_id, 100)
    replay = _grant(dsn, user_id, 100)
    assert first["status"] == "granted"
    assert replay["status"] == "already_granted"
    assert _wallet_row(dsn, user_id) == (100, 0)
    with pytest.raises(psycopg.Error):
        _grant(dsn, user_id, 101)
    assert _wallet_row(dsn, user_id) == (100, 0)


def test_concurrent_duplicate_grants_create_one_credit_event(dsn):
    user_id = _new_user(dsn)
    workers = 12
    barrier = Barrier(workers)

    def invoke(_):
        barrier.wait(timeout=10)
        return _grant(dsn, user_id, 40, "same-external-reference")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(invoke, range(workers)))
    assert sum(result["status"] == "granted" for result in results) == 1
    assert sum(result["status"] == "already_granted" for result in results) == workers - 1
    assert _wallet_row(dsn, user_id) == (40, 0)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            """SELECT count(*) FROM public.credit_ledger
               WHERE user_id = %s AND event_type = 'grant'
                 AND source_reference = 'same-external-reference'""",
            (user_id,),
        ).fetchone()[0] == 1


def test_concurrent_reservations_never_overdraw_available_credits(dsn):
    user_id = _new_user(dsn)
    _grant(dsn, user_id, 100)
    workers = 16
    barrier = Barrier(workers)

    def invoke(index):
        barrier.wait(timeout=10)
        return _reserve(dsn, user_id, f"reserve-key-{index:02d}", 10)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(invoke, range(workers)))
    assert sum(result["status"] == "reserved" for result in results) == 10
    assert sum(result["status"] == "insufficient_credits" for result in results) == 6
    assert _wallet_row(dsn, user_id) == (0, 100)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM public.credit_reservations WHERE user_id = %s",
            (user_id,),
        ).fetchone()[0] == 10


def test_concurrent_same_reservation_key_reserves_once(dsn):
    user_id = _new_user(dsn)
    _grant(dsn, user_id, 50)
    workers = 10
    barrier = Barrier(workers)

    def invoke(_):
        barrier.wait(timeout=10)
        return _reserve(dsn, user_id, "same-reservation-key", 25)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(invoke, range(workers)))
    assert sum(result["idempotent_replay"] is False for result in results) == 1
    assert sum(result["idempotent_replay"] is True for result in results) == workers - 1
    assert len({str(result["reservation_id"]) for result in results}) == 1
    assert _wallet_row(dsn, user_id) == (25, 25)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM public.credit_ledger WHERE user_id = %s AND event_type = 'reserve'",
            (user_id,),
        ).fetchone()[0] == 1


def test_reservation_idempotency_key_rejects_changed_parameters(dsn):
    user_id = _new_user(dsn)
    _grant(dsn, user_id, 60)
    _reserve(dsn, user_id, "stable-reservation-key", 20)
    with pytest.raises(psycopg.Error):
        _reserve(dsn, user_id, "stable-reservation-key", 21)
    assert _wallet_row(dsn, user_id) == (40, 20)


def test_partial_settlement_refunds_unused_reservation_and_is_idempotent(dsn):
    user_id = _new_user(dsn)
    _grant(dsn, user_id, 80)
    reserved = _reserve(dsn, user_id, "partial-settle-key", 30)
    reservation_id = reserved["reservation_id"]
    stmt = "SELECT public.settle_user_credit_reservation(%s, %s, %s)"
    settled = _wallet_call(dsn, stmt, (user_id, reservation_id, 12))
    replay = _wallet_call(dsn, stmt, (user_id, reservation_id, 12))
    assert settled["status"] == "settled"
    assert settled["captured_credits"] == 12
    assert settled["refunded_credits"] == 18
    assert replay["status"] == "already_settled"
    assert _wallet_row(dsn, user_id) == (68, 0)
    with pytest.raises(psycopg.Error):
        _wallet_call(dsn, stmt, (user_id, reservation_id, 11))


def test_full_release_returns_reservation_once(dsn):
    user_id = _new_user(dsn)
    _grant(dsn, user_id, 35)
    reserved = _reserve(dsn, user_id, "release-once-key", 15)
    reservation_id = reserved["reservation_id"]
    stmt = "SELECT public.release_user_credit_reservation(%s, %s)"
    released = _wallet_call(dsn, stmt, (user_id, reservation_id))
    replay = _wallet_call(dsn, stmt, (user_id, reservation_id))
    assert released["status"] == "released"
    assert replay["status"] == "already_released"
    assert _wallet_row(dsn, user_id) == (35, 0)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM public.credit_ledger WHERE reservation_id = %s AND event_type = 'release'",
            (reservation_id,),
        ).fetchone()[0] == 1


def test_ambiguous_provider_reservation_requires_explicit_failure_resolution_before_release(dsn):
    user_id = _new_user(dsn)
    _grant(dsn, user_id, 25)
    reserved = _reserve(dsn, user_id, "ambiguous-provider-key", 10)
    reservation_id = reserved["reservation_id"]
    _wallet_call(
        dsn,
        "SELECT public.mark_credit_reservation_reconciliation_required(%s, %s)",
        (user_id, reservation_id),
    )
    with pytest.raises(psycopg.Error):
        _wallet_call(
            dsn,
            "SELECT public.release_user_credit_reservation(%s, %s)",
            (user_id, reservation_id),
        )
    with pytest.raises(psycopg.Error):
        _wallet_call(
            dsn,
            "SELECT public.settle_user_credit_reservation(%s, %s, %s)",
            (user_id, reservation_id, 5),
        )
    resolved = _wallet_call(
        dsn,
        "SELECT public.resolve_credit_reservation_provider_outcome(%s, %s, %s, %s, %s)",
        (user_id, reservation_id, "failed", "provider-confirmed-failure-001", None),
    )
    assert resolved["status"] == "resolved"
    assert resolved["reservation_result"]["status"] == "released"
    assert _wallet_row(dsn, user_id) == (25, 0)
    replay = _wallet_call(
        dsn,
        "SELECT public.resolve_credit_reservation_provider_outcome(%s, %s, %s, %s, %s)",
        (user_id, reservation_id, "failed", "provider-confirmed-failure-001", None),
    )
    assert replay["status"] == "already_resolved"
    with pytest.raises(psycopg.Error):
        _wallet_call(
            dsn,
            "SELECT public.resolve_credit_reservation_provider_outcome(%s, %s, %s, %s, %s)",
            (user_id, reservation_id, "succeeded", "different-provider-result", 5),
        )


def test_ambiguous_provider_success_is_settled_only_through_resolution_rpc(dsn):
    user_id = _new_user(dsn)
    _grant(dsn, user_id, 40)
    reserved = _reserve(dsn, user_id, "ambiguous-success-key", 20)
    reservation_id = reserved["reservation_id"]
    _wallet_call(
        dsn,
        "SELECT public.mark_credit_reservation_reconciliation_required(%s, %s)",
        (user_id, reservation_id),
    )
    resolved = _wallet_call(
        dsn,
        "SELECT public.resolve_credit_reservation_provider_outcome(%s, %s, %s, %s, %s)",
        (user_id, reservation_id, "succeeded", "provider-confirmed-success-002", 13),
    )
    assert resolved["status"] == "resolved"
    assert resolved["reservation_result"]["status"] == "settled"
    assert _wallet_row(dsn, user_id) == (27, 0)
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT status, provider_outcome, provider_resolution_reference FROM public.credit_reservations WHERE id = %s",
            (reservation_id,),
        ).fetchone()
    assert row == ("settled", "succeeded", "provider-confirmed-success-002")


def test_wallet_rpc_execution_is_service_role_only_and_ledger_is_read_only(dsn):
    signatures = (
        "public.grant_user_credits(uuid,bigint,text,text)",
        "public.reserve_user_credits(uuid,text,text,integer,bigint)",
        "public.settle_user_credit_reservation(uuid,uuid,bigint)",
        "public.release_user_credit_reservation(uuid,uuid)",
        "public.mark_credit_reservation_reconciliation_required(uuid,uuid)",
        "public.resolve_credit_reservation_provider_outcome(uuid,uuid,text,text,bigint)",
    )
    with psycopg.connect(dsn) as conn:
        for role in ("anon", "authenticated"):
            for signature in signatures:
                assert conn.execute(
                    "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, signature),
                ).fetchone()[0] is False
        for signature in signatures:
            assert conn.execute(
                "SELECT has_function_privilege('service_role', %s, 'EXECUTE')",
                (signature,),
            ).fetchone()[0] is True
        for operation in ("INSERT", "UPDATE", "DELETE"):
            assert conn.execute(
                "SELECT has_table_privilege('service_role', 'public.credit_ledger', %s)",
                (operation,),
            ).fetchone()[0] is False
        assert conn.execute(
            "SELECT has_table_privilege('service_role', 'public.credit_ledger', 'SELECT')"
        ).fetchone()[0] is True
