\set ON_ERROR_STOP on
-- Runs only against the disposable CI database after migration 0021.
insert into public.user_profiles(user_id, username, display_name)
values (:'PWA_TEST_OWNER_ID'::uuid, 'avatar_test_user', 'Avatar Test User')
on conflict (user_id) do nothing;

do $$
declare
  v_catalog text;
  v_representation text;
begin
  select avatar_catalog_id, avatar_representation
    into v_catalog, v_representation
    from public.user_profiles
   where username = 'avatar_test_user';
  if v_catalog <> 'portrait-violet' or v_representation <> '2d' then
    raise exception 'Existing/new profile did not receive safe default avatar values';
  end if;

  update public.user_profiles
     set avatar_catalog_id = 'forest-elf', avatar_representation = '2d'
   where username = 'avatar_test_user';

  if not exists (
    select 1 from public.user_profiles
     where username = 'avatar_test_user'
       and avatar_catalog_id = 'forest-elf'
       and avatar_representation = '2d'
  ) then
    raise exception 'Curated avatar selection was not persisted';
  end if;

  begin
    update public.user_profiles set avatar_representation = 'vr'
     where username = 'avatar_test_user';
    raise exception 'Invalid avatar representation unexpectedly passed';
  exception when check_violation then
    null;
  end;

  begin
    update public.user_profiles set avatar_catalog_id = '../private'
     where username = 'avatar_test_user';
    raise exception 'Malformed avatar catalog ID unexpectedly passed';
  exception when check_violation then
    null;
  end;
end $$;
