create extension if not exists vector;

create table if not exists public.document_chunks (
    id_chunk uuid primary key default gen_random_uuid(),
    id_read uuid not null references public.document_read_results(id_read) on delete cascade,
    id_user uuid not null references public."user"(id_user) on delete cascade,
    chunk_index integer not null,
    content text not null,
    embedding vector(768) not null,
    token_count integer not null default 0,
    created_at timestamptz not null default now(),

    constraint document_chunks_chunk_index_check check (chunk_index >= 0),
    constraint document_chunks_token_count_check check (token_count >= 0),
    constraint document_chunks_unique_read_chunk unique (id_read, chunk_index)
);

create index if not exists document_chunks_read_idx
    on public.document_chunks (id_read);

create index if not exists document_chunks_user_read_idx
    on public.document_chunks (id_user, id_read);

create index if not exists document_chunks_embedding_idx
    on public.document_chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

create or replace function public.match_document_chunks(
    p_user_id uuid,
    p_read_id uuid,
    query_embedding vector(768),
    match_count integer default 5,
    match_threshold double precision default 0.2
)
returns table (
    id_chunk uuid,
    id_read uuid,
    id_user uuid,
    chunk_index integer,
    content text,
    token_count integer,
    similarity double precision
)
language sql
stable
as $$
    select
        dc.id_chunk,
        dc.id_read,
        dc.id_user,
        dc.chunk_index,
        dc.content,
        dc.token_count,
        1 - (dc.embedding <=> query_embedding) as similarity
    from public.document_chunks dc
    where dc.id_user = p_user_id
      and dc.id_read = p_read_id
      and 1 - (dc.embedding <=> query_embedding) >= match_threshold
    order by dc.embedding <=> query_embedding
    limit greatest(1, least(match_count, 20));
$$;
