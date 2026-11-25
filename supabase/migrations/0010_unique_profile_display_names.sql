-- Enforce unique public display names without changing existing account IDs.
-- The advisory lock serializes concurrent attempts to claim the same normalized name.
create or replace function public.enforce_unique_user_profile_display_name()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  normalized_name text;
begin
  normalized_name := lower(btrim(new.display_name));
  perform pg_advisory_xact_lock(hashtextextended(normalized_name, 0));

  if exists (
    select 1
    from public.user_profiles p
    where lower(btrim(p.display_name)) = normalized_name
      and p.user_id <> new.user_id
  ) then
    raise exception using
      errcode = '23505',
      message = 'This display name is already in use.';
  end if;

  return new;
end;
$$;

revoke all on function public.enforce_unique_user_profile_display_name() from public, anon, authenticated;
grant execute on function public.enforce_unique_user_profile_display_name() to service_role;

drop trigger if exists user_profiles_unique_display_name on public.user_profiles;
create trigger user_profiles_unique_display_name
before insert or update of display_name on public.user_profiles
for each row execute function public.enforce_unique_user_profile_display_name();
