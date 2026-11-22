-- PWA Studio: verify and enforce owner integrity for cloud projects.
-- Apply after 0005_cloud_projects_and_storage.sql.
-- No automatic ownership inference is safe for legacy rows.

do $$
begin
  if exists (select 1 from public.projects where owner_id is null) then
    raise exception 'Cannot enforce project ownership: public.projects contains NULL owner_id rows. Assign each project to its verified auth.users owner before applying this migration.';
  end if;
end;
$$;

alter table public.projects alter column owner_id set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.projects'::regclass
      and conname = 'projects_owner_id_fkey'
  ) then
    alter table public.projects
      add constraint projects_owner_id_fkey
      foreign key (owner_id) references auth.users(id) on delete cascade;
  end if;
end;
$$;
