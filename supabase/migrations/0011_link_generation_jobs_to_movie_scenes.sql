-- PWA Studio: bind asynchronous generation jobs and saved media to Mini Movie Studio scenes.
-- Apply after 0008-0010. No provider, worker, storage upload, or billing is enabled here.

do $$
begin
  if to_regclass('public.studio_projects') is null
     or to_regclass('public.studio_scenes') is null
     or to_regclass('public.studio_media') is null
     or to_regclass('public.generation_jobs') is null then
    raise exception 'Migration 0011 requires studio_projects, studio_scenes, studio_media, and generation_jobs. Apply the earlier schema migrations first.';
  end if;

  if exists (
    select 1 from public.studio_scenes s
    join public.studio_projects p on p.id = s.project_id
    where s.user_id <> p.user_id
  ) then
    raise exception 'Migration 0011 stopped: a scene is not owned by the same user as its studio project.';
  end if;

  if exists (
    select 1 from public.studio_media m
    join public.studio_projects p on p.id = m.project_id
    where m.user_id <> p.user_id
  ) then
    raise exception 'Migration 0011 stopped: studio_media contains a project-owner mismatch.';
  end if;
end;
$$;

-- Composite keys make ownership part of the database relationship itself.
do $$
begin
  if not exists (select 1 from pg_constraint where conrelid='public.studio_scenes'::regclass and conname='studio_scenes_id_project_user_key') then
    alter table public.studio_scenes add constraint studio_scenes_id_project_user_key unique (id, project_id, user_id);
  end if;
  if not exists (select 1 from pg_constraint where conrelid='public.generation_jobs'::regclass and conname='generation_jobs_id_user_key') then
    alter table public.generation_jobs add constraint generation_jobs_id_user_key unique (id, user_id);
  end if;
end;
$$;

alter table public.generation_jobs add column if not exists studio_scene_id uuid;

do $$
begin
  if not exists (select 1 from pg_constraint where conrelid='public.generation_jobs'::regclass and conname='generation_jobs_studio_scene_owner_fkey') then
    alter table public.generation_jobs
      add constraint generation_jobs_studio_scene_owner_fkey
      foreign key (studio_scene_id, user_id)
      references public.studio_scenes (id, user_id)
      on delete set null (studio_scene_id);
  end if;
end;
$$;

create index if not exists generation_jobs_scene_history_idx
  on public.generation_jobs(studio_scene_id, created_at desc)
  where studio_scene_id is not null;

-- Each saved media row can point to the exact scene and originating generation job.
alter table public.studio_media add column if not exists scene_id uuid;
alter table public.studio_media add column if not exists generation_job_id uuid;

do $$
begin
  if not exists (select 1 from pg_constraint where conrelid='public.studio_media'::regclass and conname='studio_media_scene_project_owner_fkey') then
    alter table public.studio_media
      add constraint studio_media_scene_project_owner_fkey
      foreign key (scene_id, project_id, user_id)
      references public.studio_scenes (id, project_id, user_id)
      on delete set null (scene_id);
  end if;

  if not exists (select 1 from pg_constraint where conrelid='public.studio_media'::regclass and conname='studio_media_generation_job_owner_fkey') then
    alter table public.studio_media
      add constraint studio_media_generation_job_owner_fkey
      foreign key (generation_job_id, user_id)
      references public.generation_jobs (id, user_id)
      on delete set null (generation_job_id);
  end if;
end;
$$;

create unique index if not exists studio_media_generation_job_unique_idx
  on public.studio_media(generation_job_id)
  where generation_job_id is not null;
create index if not exists studio_media_scene_created_idx
  on public.studio_media(scene_id, created_at desc)
  where scene_id is not null;

comment on column public.generation_jobs.studio_scene_id is
  'Optional Mini Movie Studio scene. Ownership is enforced with a composite foreign key.';
comment on column public.studio_media.scene_id is
  'Scene that uses this saved asset; project and user must match the scene owner.';
comment on column public.studio_media.generation_job_id is
  'Originating generation job; at most one media record per job. Storage remains private.';
