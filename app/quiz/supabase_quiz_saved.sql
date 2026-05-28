create table if not exists public.quiz_saved (
    id_saved uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    id_quiz uuid not null references public.quiz_generations(id_quiz) on delete cascade,
    share_code varchar(32) not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists quiz_saved_id_user_id_quiz_unique_idx
    on public.quiz_saved (id_user, id_quiz);

create index if not exists quiz_saved_id_user_created_at_idx
    on public.quiz_saved (id_user, created_at desc);
