create table if not exists public.flashcard_attempts (
    id_attempt uuid primary key default gen_random_uuid(),
    id_flashcard uuid not null references public.flashcard_generations(id_flashcard) on delete cascade,
    id_user uuid not null references public."user"(id_user) on delete cascade,
    id_read uuid references public.document_read_results(id_read) on delete set null,
    status varchar(20) not null default 'in_progress'
        check (status in ('in_progress', 'completed')),
    viewed_count integer not null default 1,
    total_cards integer not null default 0,
    current_index integer not null default 0,
    completion_percent numeric(5,2) not null default 0,
    elapsed_seconds integer not null default 0,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists flashcard_attempts_id_user_created_at_idx
    on public.flashcard_attempts (id_user, created_at desc);

create index if not exists flashcard_attempts_id_flashcard_created_at_idx
    on public.flashcard_attempts (id_flashcard, created_at desc);
