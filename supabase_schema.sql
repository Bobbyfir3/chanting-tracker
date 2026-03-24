create table if not exists chants (
  id bigint generated always as identity primary key,
  name text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists chant_logs (
  id bigint generated always as identity primary key,
  entry_id text not null unique,
  date date not null,
  chant_name text not null,
  count integer not null default 1,
  unit text not null default '遍',
  duration_minutes integer not null default 0,
  notes text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists app_settings (
  id bigint generated always as identity primary key,
  key text not null unique,
  value text not null default '',
  created_at timestamptz not null default now()
);

insert into chants (name) values
  ('百字明咒'),
  ('彌勒菩薩心咒'),
  ('瑤池金母 心咒'),
  ('摩利支天菩薩 心咒'),
  ('佛說摩利支天經'),
  ('地藏菩薩本願經 卷上'),
  ('地藏菩薩本願經 卷中'),
  ('地藏菩薩本願經 卷下'),
  ('地藏王菩薩 心咒'),
  ('高王觀世音經'),
  ('觀世音菩薩普門品'),
  ('安土地真言'),
  ('不動明王 心咒'),
  ('真佛经'),
  ('蓮花童子心咒')
on conflict (name) do nothing;

insert into app_settings (key, value)
values ('photo_data_url', '')
on conflict (key) do nothing;
