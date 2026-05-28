create table if not exists public.quiz_shares (
    id_share uuid primary key default gen_random_uuid(),
    id_quiz uuid not null references public.quiz_generations(id_quiz) on delete cascade,
    id_user uuid not null references public."user"(id_user) on delete cascade,
    share_code varchar(32) not null unique,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists quiz_shares_id_quiz_unique_idx
    on public.quiz_shares (id_quiz);

create index if not exists quiz_shares_share_code_idx
    on public.quiz_shares (share_code);
