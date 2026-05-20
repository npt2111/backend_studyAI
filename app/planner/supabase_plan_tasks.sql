create table if not exists public.plan_tasks (
    id_task uuid primary key default gen_random_uuid(),
    id_user uuid not null references public."user"(id_user) on delete cascade,
    task_name text not null,
    subject text,
    task_date date not null,
    start_time time not null,
    end_time time not null,
    priority text not null check (priority in ('low', 'medium', 'high')),
    created_at timestamptz not null default now()
);

create index if not exists plan_tasks_id_user_task_date_idx
    on public.plan_tasks (id_user, task_date);
