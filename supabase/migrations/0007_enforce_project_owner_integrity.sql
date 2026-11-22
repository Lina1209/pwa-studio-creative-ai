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
