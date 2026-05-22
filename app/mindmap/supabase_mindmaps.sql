create table if not exists public.mindmaps (
    id_mindmap uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    id_read uuid not null references public.document_read_results(id_read) on delete cascade,
    file_name text,
    status varchar(20) not null default 'processing'
        check (status in ('processing', 'done', 'failed')),
    mindmap_json jsonb not null default '{}'::jsonb,
    markdown text,
    raw_response text,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id_read)
);

create index if not exists mindmaps_id_user_created_at_idx
    on public.mindmaps (id_user, created_at desc);
