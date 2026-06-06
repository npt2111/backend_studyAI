create table if not exists public.document_summaries (
    id_summary uuid primary key default gen_random_uuid(),
    id_read uuid not null references public.document_read_results(id_read) on delete cascade,
    id_user uuid not null references public."user"(id_user) on delete cascade,
    file_name text,
    summary text not null default '',
    key_points jsonb not null default '[]'::jsonb,
    raw_response text,
    status varchar(20) not null default 'done' check (status in ('done', 'failed')),
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id_read)
);

create index if not exists document_summaries_user_read_idx
    on public.document_summaries (id_user, id_read);
