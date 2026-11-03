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

-- Два канала заявок: md — Молдова (этот сайт), ru — Россия (lh47-russia.vercel.app). Запустить один раз.
alter table public.leads add column if not exists market text not null default 'md' check (market in ('md', 'ru'));

-- ДЗ №2: CRM-воронка — этапы, источник, заметки, история переходов. Запустить один раз.
alter table public.leads drop constraint if exists leads_status_check;
update public.leads set status = case status when 'новая' then 'Новая' when 'в работе' then 'Связались'
  when 'закрыта' then 'Оплачено' else status end;
alter table public.leads alter column status set default 'Новая';
alter table public.leads add constraint leads_status_check
  check (status in ('Новая', 'Связались', 'Встреча', 'КП отправлено', 'Оплачено', 'Отказ'));
alter table public.leads add column if not exists source text not null default 'Сайт'
  check (source in ('Сайт', 'Вручную', 'Визитка', 'Telegram'));
alter table public.leads add column if not exists notes text not null default '';
alter table public.leads add column if not exists history jsonb not null default '[]'::jsonb;
-- у старых заявок история начинается с текущего этапа на дату создания
update public.leads set history = jsonb_build_array(jsonb_build_object('stage', status, 'at', created_at))
  where history = '[]'::jsonb;

-- ДЗ №2, блок 2: визитки → CRM. Оригиналы — в закрытом хранилище «cards». Запустить один раз.
alter table public.leads add column if not exists doc text;
insert into storage.buckets (id, name, public) values ('cards', 'cards', false) on conflict (id) do nothing;
notify pgrst, 'reload schema';
