create table if not exists ai_training_events (
    id_training uuid primary key default gen_random_uuid(),
    id_user uuid not null,
    source_type text not null,
    source_id text not null,
    id_read uuid null,
    training_payload jsonb not null default '{}'::jsonb,
    ai_output jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists ai_training_events_user_created_idx
    on ai_training_events (id_user, created_at desc);

create index if not exists ai_training_events_source_idx
    on ai_training_events (source_type, source_id);
