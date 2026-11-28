-- Supports owner-scoped keyset pagination by immutable creation time and ID.
-- Apply only through the reviewed migration process; CI uses disposable PostgreSQL.
create index if not exists characters_owner_created_id_desc_idx
  on public.characters (owner_id, created_at desc, id desc);
