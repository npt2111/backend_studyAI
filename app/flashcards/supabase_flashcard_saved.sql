create table if not exists public.flashcard_saved (
    id_saved uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    id_flashcard uuid not null references public.flashcard_generations(id_flashcard) on delete cascade,
    share_code varchar(32) not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists flashcard_saved_id_user_id_flashcard_unique_idx
    on public.flashcard_saved (id_user, id_flashcard);

create index if not exists flashcard_saved_id_user_created_at_idx
    on public.flashcard_saved (id_user, created_at desc);
