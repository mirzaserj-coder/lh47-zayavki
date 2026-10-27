-- Run once in Supabase → SQL Editor.
create table if not exists public.leads (
  id         bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  name       text not null,
  phone      text not null,
  comment    text not null,
  status     text not null default 'новая' check (status in ('новая', 'в работе', 'закрыта'))
);
create index if not exists leads_created_at_idx on public.leads (created_at desc);

-- Row Level Security on, no policies: the public anon key can neither read nor write.
-- Only the site's server functions (service_role key from Vercel settings) work with the table.
alter table public.leads enable row level security;
