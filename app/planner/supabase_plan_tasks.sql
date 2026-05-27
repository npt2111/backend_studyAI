create table if not exists public.plan_tasks (
    id_task uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    task_name text not null,
    subject text,
    task_date date not null,
    start_time time not null,
    end_time time not null,
    priority text not null check (priority in ('low', 'medium', 'high')),
    status varchar(20) not null default 'pending' check (status in ('pending', 'done')),
    created_at timestamptz not null default now()
);

create index if not exists plan_tasks_id_user_task_date_idx
    on public.plan_tasks (id_user, task_date);

alter table public.plan_tasks
    add column if not exists reminder_sent_at timestamptz;

create table if not exists public.user_fcm_tokens (
    id_token uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    token text not null unique,
    device_type text not null default 'android',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists user_fcm_tokens_id_user_active_idx
    on public.user_fcm_tokens (id_user, is_active);
