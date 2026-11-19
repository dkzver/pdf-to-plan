-- v2: облако только для шаринга и галереи. В v1 документ дома живёт в файле и IndexedDB.
-- Supabase/Postgres 15+. RLS включён на всех таблицах.

create table homes (
  id           uuid primary key default gen_random_uuid(),
  owner_id     uuid not null references auth.users (id) on delete cascade,
  name         text not null,
  data         jsonb not null,                 -- документ Home целиком, версия внутри
  format_version int  not null default 1,
  share_token  text unique,                    -- null = не опубликован
  is_public    boolean not null default false, -- галерея
  thumb_path   text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint homes_name_len check (char_length(name) between 1 and 120)
);
create index homes_owner_updated_idx on homes (owner_id, updated_at desc);
create index homes_public_idx on homes (is_public) where is_public;

create table home_versions (
  id         uuid primary key default gen_random_uuid(),
  home_id    uuid not null references homes (id) on delete cascade,
  data       jsonb not null,
  label      text,
  created_at timestamptz not null default now()
);
create index home_versions_home_idx on home_versions (home_id, created_at desc);

create table catalog_items (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,
  name        text not null,
  category    text not null,                   -- living, kitchen, bedroom, bath, outdoor...
  model_path  text not null,                   -- glTF/GLB в нашем хранилище
  thumb_path  text,
  width_cm    integer not null check (width_cm  > 0),
  depth_cm    integer not null check (depth_cm  > 0),
  height_cm   integer not null check (height_cm > 0),
  is_public   boolean not null default true,
  created_at  timestamptz not null default now()
);
create index catalog_items_category_idx on catalog_items (category, name);

create table textures (
  id         uuid primary key default gen_random_uuid(),
  slug       text not null unique,
  name       text not null,
  image_path text not null,
  shininess  numeric(3,2) not null default 0.2 check (shininess between 0 and 1),
  created_at timestamptz not null default now()
);

-- Доступ
alter table homes          enable row level security;
alter table home_versions  enable row level security;
alter table catalog_items  enable row level security;
alter table textures       enable row level security;

create policy homes_owner_all on homes
  for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

create policy homes_public_read on homes
  for select using (is_public or share_token is not null);

create policy home_versions_owner on home_versions
  for all using (exists (select 1 from homes h
                         where h.id = home_id and h.owner_id = auth.uid()));

create policy catalog_public_read on catalog_items
  for select using (is_public);

create policy textures_public_read on textures
  for select using (true);

-- Чтение по share_token идёт через edge-функцию с service-role: анонимный клиент
-- не получает доступ ко всей таблице, только к одному дому по токену.
