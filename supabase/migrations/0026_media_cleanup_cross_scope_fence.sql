-- PWA Studio: cross-scope fence for private-media deletion events.
-- DRAFT ONLY. Apply only to disposable CI PostgreSQL; never production.
-- This migration does not add a replacement worker or activate Storage deletion.

alter table public.media_asset_outbox
  drop constraint if exists media_asset_outbox_event_type_check;

alter table public.media_asset_outbox
  add constraint media_asset_outbox_event_type_check
  check (event_type in (
    'media_cleanup_requested',
    'media_upload_verify_requested',
    'media_reference_replacement_cleanup_requested'
  ));

-- Refuse to install the fence over ambiguous existing work. Do not silently
-- choose a winner: operators must reconcile duplicate active deletion intents.
do $$
begin
  if exists (
    select 1
    from public.media_asset_outbox e
    where e.event_type in (
      'media_cleanup_requested',
      'media_reference_replacement_cleanup_requested'
    )
      and e.status in ('pending','claimed')
    group by e.asset_id
    having count(*) > 1
  ) then
    raise exception
      'cannot install cross-scope media cleanup fence: duplicate active deletion events exist'
      using errcode='23505';
  end if;
end;
$$;

-- A single immutable media object may have at most one active deletion
-- authorization, regardless of whether it came from character deletion or
-- reference replacement. Delivered/dead-letter events remain auditable and
-- do not block a later, separately authorized operation.
create unique index if not exists media_asset_outbox_one_active_cleanup_per_asset
  on public.media_asset_outbox(asset_id)
  where event_type in (
    'media_cleanup_requested',
    'media_reference_replacement_cleanup_requested'
  )
    and status in ('pending','claimed');

comment on index public.media_asset_outbox_one_active_cleanup_per_asset is
  'Cross-scope fence: at most one pending/claimed deletion authorization per media asset across character deletion and reference replacement.';
