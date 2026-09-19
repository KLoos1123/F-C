-- Eenmalig te draaien in de Supabase SQL editor (Dashboard -> SQL Editor -> New query).
--
-- Zet de tenders/beschrijvingen-tabellen op zoals supabase_sync.py ze vult,
-- plus read-only toegang voor de anon-key (nodig voor Copilot Studio en een
-- eventueel toekomstig live dashboard). De service_role-key (gebruikt door
-- run.py/supabase_sync.py in GitHub Actions) omzeilt RLS automatisch en hoeft
-- dus geen aparte policy.
--
-- status/status_gewijzigd_door/status_gewijzigd_op staan er nu al bij, ook al
-- heeft het huidige (static/no-login) dashboard nog geen workflow-UI die ze
-- zet -- zelfde kolommen als Scrappingtool-v2, zodat een latere upgrade naar
-- een interactief dashboard geen migratie nodig heeft. upsert_tenders_bulk
-- raakt ze bewust nooit aan, om dezelfde reden als in Scrappingtool-v2: het
-- zijn straks door gebruikers gezette waarden, geen scraper-output.

create table if not exists public.tenders (
    bron                  text not null,
    tender_id             text not null,
    nummer                text,
    titel                 text,
    organisatie           text,
    bron_status           text,
    deadline              text,
    publicatiedatum       text,
    locatie               text,
    url                   text,
    subsidie_relevant     boolean not null default false,
    subsidie_categorieen  text,
    subsidie_trefwoorden  text,
    subsidie_score        integer not null default 0,
    status                text,
    status_gewijzigd_door text,
    status_gewijzigd_op   timestamptz,
    eerst_gezien          timestamptz not null default now(),
    laatst_gezien         timestamptz not null default now(),
    primary key (bron, tender_id)
);

create index if not exists idx_tenders_relevant on public.tenders(subsidie_relevant);
create index if not exists idx_tenders_publicatie on public.tenders(publicatiedatum desc);
create index if not exists idx_tenders_bron on public.tenders(bron);

create table if not exists public.beschrijvingen (
    bron          text not null,
    tender_id     text not null,
    omschrijving  text,
    opgehaald_op  timestamptz not null default now(),
    primary key (bron, tender_id)
);

-- ---------------------------------------------------------------- RLS

alter table public.tenders       enable row level security;
alter table public.beschrijvingen enable row level security;

drop policy if exists "tenders_read_all"       on public.tenders;
drop policy if exists "beschrijvingen_read_all" on public.beschrijvingen;

-- Publieke tenderdata (titel/organisatie/deadline/...), geen persoons- of
-- dealgegevens -- read-only voor iedereen met de anon-key is hier bewust
-- toegestaan, in tegenstelling tot bv. de MKB-scraper die vertrouwelijke
-- klantdata bevat.
create policy "tenders_read_all" on public.tenders
    for select using (true);

create policy "beschrijvingen_read_all" on public.beschrijvingen
    for select using (true);

grant select on public.tenders, public.beschrijvingen to anon, authenticated;

-- RLS (hierboven) is een aanvullende check bovenop de gewone tabel-grants,
-- geen vervanging: service_role heeft bypassrls (slaat de policies over) maar
-- heeft zonder deze GRANT alsnog geen basis-schrijfrecht op de tabellen.
grant select, insert, update on public.tenders, public.beschrijvingen to service_role;

-- ---------------------------------------------------------------- upsert RPC

-- security invoker (expliciet, i.p.v. het definer-default): de functie loopt
-- dus met de rechten van de aanroeper. Dat is voldoende, want service_role
-- heeft in Supabase standaard bypassrls -- en het voorkomt dat een later per
-- ongeluk verleende EXECUTE-grant een zwakkere rol de rechten van de
-- functie-eigenaar zou geven.
create or replace function public.upsert_tenders_bulk(rows jsonb)
returns integer
language plpgsql
security invoker
set search_path = public
as $$
declare
    n integer;
begin
    with invoer as (
        select
            (r->>'bron')                 as bron,
            (r->>'tender_id')             as tender_id,
            (r->>'nummer')                as nummer,
            (r->>'titel')                 as titel,
            (r->>'organisatie')           as organisatie,
            (r->>'bron_status')           as bron_status,
            (r->>'deadline')              as deadline,
            (r->>'publicatiedatum')       as publicatiedatum,
            (r->>'locatie')               as locatie,
            (r->>'url')                   as url,
            coalesce((r->>'subsidie_relevant')::boolean, false) as subsidie_relevant,
            (r->>'subsidie_categorieen')  as subsidie_categorieen,
            (r->>'subsidie_trefwoorden')  as subsidie_trefwoorden,
            coalesce((r->>'subsidie_score')::integer, 0) as subsidie_score
        from jsonb_array_elements(rows) as r
    )
    insert into public.tenders as t
        (bron, tender_id, nummer, titel, organisatie, bron_status,
         deadline, publicatiedatum, locatie, url,
         subsidie_relevant, subsidie_categorieen, subsidie_trefwoorden, subsidie_score,
         eerst_gezien, laatst_gezien)
    select
        bron, tender_id, nummer, titel, organisatie, bron_status,
        deadline, publicatiedatum, locatie, url,
        subsidie_relevant, subsidie_categorieen, subsidie_trefwoorden, subsidie_score,
        now(), now()
    from invoer
    where bron is not null and tender_id is not null
    on conflict (bron, tender_id) do update set
        nummer               = excluded.nummer,
        titel                = excluded.titel,
        organisatie          = excluded.organisatie,
        bron_status          = excluded.bron_status,
        deadline             = excluded.deadline,
        publicatiedatum      = excluded.publicatiedatum,
        locatie              = excluded.locatie,
        url                  = excluded.url,
        subsidie_relevant    = excluded.subsidie_relevant,
        subsidie_categorieen = excluded.subsidie_categorieen,
        subsidie_trefwoorden = excluded.subsidie_trefwoorden,
        subsidie_score       = excluded.subsidie_score,
        laatst_gezien        = now();
        -- status/status_gewijzigd_door/status_gewijzigd_op/eerst_gezien bewust niet in de update-set

    get diagnostics n = row_count;
    return n;
end;
$$;

-- Alleen de service_role (gebruikt door run.py in GitHub Actions) mag deze
-- functie aanroepen -- Postgres geeft functies standaard EXECUTE aan PUBLIC,
-- dus dat moet je expliciet intrekken (anders zou iedereen met de publieke
-- anon-key hierdoor in de tabel kunnen schrijven) en weer expliciet teruggeven
-- aan service_role: REVOKE ALL FROM PUBLIC trekt ook in wat service_role via
-- PUBLIC-lidmaatschap zou hebben, dus zonder deze GRANT sluit je per ongeluk
-- ook je eigen sync buiten.
revoke all on function public.upsert_tenders_bulk(jsonb) from public;
grant execute on function public.upsert_tenders_bulk(jsonb) to service_role;
