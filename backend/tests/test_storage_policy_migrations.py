from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"


def _sql(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8").lower()


def test_storage_buckets_are_private_and_have_explicit_mime_and_size_limits():
    for name in ("0002_storage_and_moderation.sql", "0005_cloud_projects_and_storage.sql"):
        sql = _sql(name)
        assert "public = false" in sql
        assert "file_size_limit" in sql
        assert "allowed_mime_types" in sql


def test_storage_object_policies_bind_first_path_segment_to_authenticated_user():
    for name in ("0002_storage_and_moderation.sql", "0005_cloud_projects_and_storage.sql"):
        sql = _sql(name)
        for operation in ("select", "insert", "update", "delete"):
            assert f"for {operation} to authenticated" in sql
        assert sql.count("(storage.foldername(name))[1] = auth.uid()::text") >= 4


def test_storage_policies_never_make_studio_media_public():
    for name in ("0002_storage_and_moderation.sql", "0005_cloud_projects_and_storage.sql"):
        sql = _sql(name)
        assert "bucket_id = 'studio-media'" in sql or "'studio-media','studio-exports'" in sql
        assert "create policy" in sql
        assert "for select to authenticated" in sql
        assert "for insert to authenticated" in sql
        assert "for update to authenticated" in sql
        assert "for delete to authenticated" in sql
