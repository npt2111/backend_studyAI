create table if not exists public.notification_reads (
    id_read uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    notification_id text not null,
    read_at timestamptz not null default now(),
    unique (id_user, notification_id)
);

create index if not exists notification_reads_id_user_read_at_idx
    on public.notification_reads (id_user, read_at desc);
