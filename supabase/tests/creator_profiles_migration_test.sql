begin;

do $$
declare
  v_user uuid := '88888888-8888-4888-8888-888888888888';
  v_username text;
begin
  insert into auth.users(id) values(v_user) on conflict do nothing;
  select username into v_username from public.profiles where id = v_user;
  if v_username is null or v_username !~ '^creator_[0-9a-f]{8}$' then
    raise exception 'existing profile username backfill failed';
  end if;
  if not exists (
    select 1 from pg_indexes where schemaname='public'
      and indexname='profiles_username_lower_unique'
  ) then raise exception 'case-insensitive username uniqueness index missing'; end if;
  if not has_table_privilege('authenticated','public.profiles','select') then
    raise exception 'existing own-profile select grant unexpectedly removed'; end if;
  if not exists(select 1 from pg_constraint where conrelid='public.profiles'::regclass and conname='profiles_visibility_values') then
    raise exception 'profile visibility constraint missing'; end if;
  if not has_table_privilege('service_role','public.profiles','update') then
    raise exception 'service role cannot update profiles'; end if;
end;
$$;

rollback;
