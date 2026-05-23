create table if not exists public.document_chat_sessions (
    id_chat_session uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    id_read uuid not null references public.document_read_results(id_read) on delete cascade,
    file_name text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id_user, id_read)
);

create table if not exists public.document_chat_messages (
    id_message uuid primary key default gen_random_uuid(),
    id_chat_session uuid not null references public.document_chat_sessions(id_chat_session) on delete cascade,
    id_user uuid not null references public."user"(id_user) on delete cascade,
    id_read uuid not null references public.document_read_results(id_read) on delete cascade,
    role varchar(20) not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz not null default now()
);

create index if not exists document_chat_sessions_user_updated_idx
    on public.document_chat_sessions (id_user, updated_at desc);

create index if not exists document_chat_messages_session_created_idx
    on public.document_chat_messages (id_chat_session, created_at asc);
