from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0014_admin_analytics_summary.sql"


def test_admin_analytics_rpc_is_aggregate_only_and_service_role_only():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "count(distinct owner_id)" in sql
    assert "count(distinct user_id)" in sql
    assert "revoke all on function public.admin_analytics_summary" in sql
    assert "to service_role" in sql
    assert "grant execute" in sql
    for forbidden in ("email", "username", "prompt", "message_body", "ip_address", "user_agent"):
        assert forbidden not in sql
