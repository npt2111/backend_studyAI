create table if not exists public.flashcard_generations (
    id_flashcard uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    id_read uuid not null references public.document_read_results(id_read) on delete cascade,
    file_name text,
    difficulty varchar(20) not null check (difficulty in ('easy', 'medium', 'hard')),
    card_count integer not null check (card_count in (10, 20, 30)),
    status varchar(20) not null default 'processing'
        check (status in ('processing', 'done', 'failed')),
    cards jsonb not null default '[]'::jsonb,
    raw_response text,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists flashcard_generations_id_user_created_at_idx
    on public.flashcard_generations (id_user, created_at desc);

create index if not exists flashcard_generations_id_read_created_at_idx
    on public.flashcard_generations (id_read, created_at desc);
