-- PWA Studio: enforce tenant ownership across parent/child relationships.
-- Review and apply manually only after checking the preflight queries below.
-- This migration does not run automatically and has not been applied to production.

do $$
begin
  if exists (
    select 1
    from public.assistant_messages m
    join public.assistant_conversations c on c.id = m.conversation_id
    where m.user_id <> c.user_id
  ) then
    raise exception 'Migration 0008 stopped: assistant_messages contains rows whose user_id differs from the conversation owner. Review and repair each row using verified ownership before retrying.';
  end if;

  if exists (
    select 1
    from public.studio_characters ch
    join public.studio_projects p on p.id = ch.project_id
    where ch.user_id <> p.user_id
  ) then
    raise exception 'Migration 0008 stopped: studio_characters contains cross-owner project references. Review and repair each row before retrying.';
  end if;

  if exists (
    select 1
    from public.studio_scenes s
    join public.studio_projects p on p.id = s.project_id
    where s.user_id <> p.user_id
  ) then
    raise exception 'Migration 0008 stopped: studio_scenes contains cross-owner project references. Review and repair each row before retrying.';
  end if;
end;
$$;

-- Composite unique keys allow PostgreSQL to enforce both identity and ownership.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.assistant_conversations'::regclass
      and conname = 'assistant_conversations_id_user_id_key'
  ) then
    alter table public.assistant_conversations
      add constraint assistant_conversations_id_user_id_key unique (id, user_id);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.studio_projects'::regclass
      and conname = 'studio_projects_id_user_id_key'
  ) then
    alter table public.studio_projects
      add constraint studio_projects_id_user_id_key unique (id, user_id);
  end if;
end;
$$;

-- A message must belong to the same user as its parent conversation.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.assistant_messages'::regclass
      and conname = 'assistant_messages_conversation_owner_fkey'
  ) then
    alter table public.assistant_messages
      add constraint assistant_messages_conversation_owner_fkey
      foreign key (conversation_id, user_id)
      references public.assistant_conversations (id, user_id)
      on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.studio_characters'::regclass
      and conname = 'studio_characters_project_owner_fkey'
  ) then
    alter table public.studio_characters
      add constraint studio_characters_project_owner_fkey
      foreign key (project_id, user_id)
      references public.studio_projects (id, user_id)
      on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.studio_scenes'::regclass
      and conname = 'studio_scenes_project_owner_fkey'
  ) then
    alter table public.studio_scenes
      add constraint studio_scenes_project_owner_fkey
      foreign key (project_id, user_id)
      references public.studio_projects (id, user_id)
      on delete cascade;
  end if;
end;
$$;

create index if not exists assistant_messages_user_conversation_idx
  on public.assistant_messages(user_id, conversation_id, created_at);

create index if not exists studio_characters_project_owner_idx
  on public.studio_characters(project_id, user_id);

create index if not exists studio_scenes_project_owner_idx
  on public.studio_scenes(project_id, user_id);
