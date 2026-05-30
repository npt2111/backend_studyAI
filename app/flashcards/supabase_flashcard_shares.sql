create table if not exists public.flashcard_shares (
    id_share uuid primary key default gen_random_uuid(),
    id_flashcard uuid not null references public.flashcard_generations(id_flashcard) on delete cascade,
    id_user uuid not null references public."user"(id_user) on delete cascade,
    share_code varchar(32) not null unique,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists flashcard_shares_id_flashcard_unique_idx
    on public.flashcard_shares (id_flashcard);

create index if not exists flashcard_shares_share_code_idx
    on public.flashcard_shares (share_code);
