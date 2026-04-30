create table fda_raw_events (
    id uuid primary key default gen_random_uuid(),
    safety_report_id text,
    payload jsonb not null,
    ingested_at timestamp default now(),

    unique (safety_report_id)
);


create table safety_reports (
    safety_report_id text primary key,

    received_date date,
    receipt_date date,
    transmission_date date,

    serious boolean,
    seriousness_death boolean,
    seriousness_life_threatening boolean,
    seriousness_hospitalization boolean,

    company_number text,
    reporter_country text,

    meta jsonb, -- for rarely used fields

    created_at timestamp default now()
);



create table patients (
    id uuid primary key default gen_random_uuid(),
    safety_report_id text references safety_reports(safety_report_id),

    age numeric,
    age_unit text,
    sex text,
    death_date date,

    raw jsonb
);



create table reactions_dim (
    id serial primary key,
    reaction_name text unique
);


create table safety_report_reactions (
    id uuid primary key default gen_random_uuid(),
    safety_report_id text references safety_reports(safety_report_id),
    reaction_id int references reactions_dim(id)
);



create table drugs_dim (
    id uuid primary key default gen_random_uuid(),

    medicinal_product text,
    generic_name text,
    brand_name text,

    manufacturer_name text,
    substance_name text,

    openfda jsonb,

    unique (medicinal_product, generic_name, brand_name)
);




create table safety_report_drugs (
    id uuid primary key default gen_random_uuid(),
    safety_report_id text references safety_reports(safety_report_id),
    drug_id uuid references drugs_dim(id),

    drug_characterization text,
    authorization_number text,
    route text,
    indication text,

    start_date date,
    end_date date,
    treatment_duration numeric,
    treatment_duration_unit text,

    raw jsonb
);



create table age_units (
    code text primary key,
    description text
);

create table gender_codes (
    code text primary key,
    description text
);

create table route_codes (
    code text primary key,
    description text
);


create index idx_reports_received_date on safety_reports(received_date);
create index idx_reports_country on safety_reports(reporter_country);

create index idx_reactions_name on reactions_dim(reaction_name);

create index idx_drugs_product on drugs_dim(medicinal_product);

create index idx_drug_fact_report on safety_report_drugs(safety_report_id);
create index idx_reaction_fact_report on safety_report_reactions(safety_report_id);



alter table fda_raw_events disable row level security;
alter table safety_reports disable row level security;
alter table patients disable row level security;
alter table reactions_dim disable row level security;
alter table safety_report_reactions disable row level security;
alter table drugs_dim disable row level security;
alter table safety_report_drugs disable row level security;
