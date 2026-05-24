create table if not exists public.weekly_goals (
    id_goal uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    week_start_date date not null,
    goal_hours numeric(6,2) not null default 20,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id_user, week_start_date)
);

create index if not exists weekly_goals_id_user_week_start_idx
    on public.weekly_goals (id_user, week_start_date desc);

create table if not exists public.daily_checkins (
    id_checkin uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    checkin_date date not null,
    created_at timestamptz not null default now(),
    unique (id_user, checkin_date)
);

create index if not exists daily_checkins_id_user_date_idx
    on public.daily_checkins (id_user, checkin_date desc);

create table if not exists public.study_activities (
    id_activity uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    activity_type varchar(30) not null
        check (activity_type in ('document', 'quiz', 'flashcard', 'mindmap', 'chat', 'study')),
    title text not null,
    description text,
    duration_seconds integer not null default 0,
    id_read uuid references public.document_read_results(id_read) on delete set null,
    source_id uuid,
    metadata jsonb not null default '{}'::jsonb,
    activity_date date not null default current_date,
    created_at timestamptz not null default now()
);

create index if not exists study_activities_id_user_created_at_idx
    on public.study_activities (id_user, created_at desc);

create index if not exists study_activities_id_user_activity_date_idx
    on public.study_activities (id_user, activity_date desc);
