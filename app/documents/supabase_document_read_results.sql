create table if not exists public.document_read_results (
    id_read uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    file_name text not null,
    storage_path text not null,
    mime_type text,
    extracted_text text,
    source_word_count integer not null default 0,
    status varchar(20) not null default 'processing'
        check (status in ('processing', 'done', 'failed')),
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists document_read_results_id_user_created_at_idx
    on public.document_read_results (id_user, created_at desc);

