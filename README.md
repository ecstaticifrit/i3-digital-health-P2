# OpenFDA Adverse Event Ingestion Pipeline

This project fetches adverse drug event reports from the OpenFDA Drug Event API and loads them into a Supabase Postgres database. It stores both the original raw FDA event payload and a normalized analytical schema for reports, patients, drugs, and reactions.

The current pipeline fetches reports received between `2004-01-01` and `2008-12-31` from:

```text
https://api.fda.gov/drug/event.json
```

## Use Cases

This project is useful for building a structured adverse-event dataset from OpenFDA data. Example use cases include:

- Tracking reported adverse reactions by drug, brand, generic name, or manufacturer.
- Analyzing serious adverse events by country, reporting date, or outcome type.
- Finding common reactions associated with specific medicinal products.
- Comparing drug indications, routes, and treatment durations across adverse reports.
- Keeping raw OpenFDA payloads for auditability while querying normalized tables for analytics.
- Prototyping pharmacovigilance dashboards or exploratory health-data analysis workflows.

## Project Structure

```text
.
├── app.py                  # Python ingestion pipeline
├── requirements.txt        # Python dependencies
├── supabase_scripts.sql    # Supabase/Postgres schema and indexes
└── README.md               # Project documentation
```

## Requirements

- Python 3.9+
- A Supabase project
- Supabase database access with permission to create tables
- OpenFDA API access. The current script uses the public API without an API key.

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Create the database schema in Supabase.

Open the Supabase SQL Editor and run the contents of:

```text
supabase_scripts.sql
```

3. Create a `.env` file in the project root with your Supabase credentials:

```env
SUPABASE_URL=your-supabase-project-url
SUPABASE_KEY=your-supabase-service-role-or-api-key
```

Use a key that has permission to insert and upsert rows into the target tables. Keep this file private and do not commit it to version control.

## Running the Pipeline

Run the ingestion script:

```bash
python app.py
```

By default, `app.py` calls:

```python
run_pipeline(limit=5)
```

This fetches 5 reports and inserts them into Supabase.

To ingest more records, change the limit at the bottom of `app.py`:

```python
if __name__ == "__main__":
    run_pipeline(limit=100)
```

The fetch query currently uses this fixed date range:

```python
"search": "receivedate:[20040101 TO 20081231]"
```

You can adjust that range in `fetch_data()` if you want different reporting periods.

## How It Works

The pipeline follows these steps for each FDA report:

1. Fetch reports from the OpenFDA Drug Event API.
2. Store the full raw JSON event in `fda_raw_events`.
3. Extract high-value report metadata into `safety_reports`.
4. Extract patient-level information into `patients`.
5. Normalize reaction names into `reactions_dim`.
6. Link reports to reactions through `safety_report_reactions`.
7. Normalize drug identity fields into `drugs_dim`.
8. Link reports to drugs through `safety_report_drugs`.

The script uses retry logic with exponential backoff for temporary API failures.

## Schema Structure

### `fda_raw_events`

Stores the original OpenFDA event payload.

Key fields:

- `safety_report_id`: FDA safety report identifier.
- `payload`: Full raw JSON payload.
- `ingested_at`: Timestamp when the record was inserted.

Purpose: preserves the original source data for auditability, reprocessing, and fields that are not yet normalized.

### `safety_reports`

Stores one row per FDA safety report.

Key fields:

- `safety_report_id`: Primary key from OpenFDA.
- `received_date`, `receipt_date`, `transmission_date`: Normalized date fields.
- `serious`: Whether the event was marked serious.
- `seriousness_death`, `seriousness_life_threatening`, `seriousness_hospitalization`: Seriousness flags.
- `company_number`: Company report number.
- `reporter_country`: Country of the primary reporter.
- `meta`: Full report JSON for rarely used fields.

Purpose: provides the central fact table for event-level analysis.

### `patients`

Stores patient-level details for each safety report.

Key fields:

- `safety_report_id`: References `safety_reports`.
- `age`, `age_unit`: Patient age and OpenFDA age unit code.
- `sex`: Patient sex code.
- `death_date`: Patient death date, when present.
- `raw`: Original patient JSON object.

Purpose: separates patient data from event metadata while keeping the original patient object available.

### `reactions_dim`

Stores unique reaction names.

Key fields:

- `id`: Reaction surrogate key.
- `reaction_name`: MedDRA preferred term from OpenFDA, stored uniquely.

Purpose: avoids repeated reaction text across many reports and supports aggregation by reaction.

### `safety_report_reactions`

Join table between reports and reactions.

Key fields:

- `safety_report_id`: References `safety_reports`.
- `reaction_id`: References `reactions_dim`.

Purpose: models the many-to-many relationship where one report can include multiple reactions and one reaction can appear in many reports.

### `drugs_dim`

Stores unique drug identity records.

Key fields:

- `id`: Drug surrogate key.
- `medicinal_product`: FDA medicinal product name.
- `generic_name`: OpenFDA generic name, when available.
- `brand_name`: OpenFDA brand name, when available.
- `manufacturer_name`: OpenFDA manufacturer name, when available.
- `substance_name`: OpenFDA substance name, when available.
- `openfda`: Original OpenFDA drug metadata object.

Purpose: normalizes drug identity information and avoids duplicating drug metadata for every report.

### `safety_report_drugs`

Join table between reports and drugs, with report-specific drug exposure details.

Key fields:

- `safety_report_id`: References `safety_reports`.
- `drug_id`: References `drugs_dim`.
- `drug_characterization`: Role of the drug in the report, such as suspect or concomitant.
- `authorization_number`: Drug authorization number.
- `route`: Administration route code.
- `indication`: Reported indication.
- `start_date`, `end_date`: Treatment dates, when provided.
- `treatment_duration`, `treatment_duration_unit`: Treatment duration fields.
- `raw`: Original drug JSON object.

Purpose: keeps drug identity in `drugs_dim` while preserving report-specific drug details in the join table.

### Code Tables

The schema also defines lookup tables for OpenFDA-style coded values:

- `age_units`
- `gender_codes`
- `route_codes`

These tables are intended for code descriptions. The current script creates them but does not populate them.

## Why This Schema Was Chosen

OpenFDA adverse event records are nested JSON documents. A single report can contain one patient, multiple drugs, and multiple reactions. A purely flat table would duplicate report and patient fields for every drug-reaction combination, which makes aggregation error-prone.

This schema uses a hybrid design:

- Raw JSON is preserved in `fda_raw_events` for traceability and future reprocessing.
- Frequently queried report fields are extracted into `safety_reports` for easier analytics.
- Repeating entities such as drugs and reactions are normalized into dimension tables.
- Many-to-many relationships are represented with join tables.
- Original nested objects are still kept in `raw`, `meta`, and `openfda` JSONB columns so no source context is lost.

This approach gives the project both analytical performance and flexibility. Analysts can query normalized tables for common questions while still accessing the original FDA payload when a field was not explicitly modeled.

## Example Queries

### Most Common Reactions

```sql
select
    r.reaction_name,
    count(*) as report_count
from safety_report_reactions srr
join reactions_dim r on r.id = srr.reaction_id
group by r.reaction_name
order by report_count desc
limit 20;
```

### Serious Reports by Country

```sql
select
    reporter_country,
    count(*) as serious_report_count
from safety_reports
where serious = true
group by reporter_country
order by serious_report_count desc;
```

### Drugs Associated With a Specific Reaction

```sql
select
    d.medicinal_product,
    d.generic_name,
    d.brand_name,
    count(distinct sr.safety_report_id) as report_count
from safety_reports sr
join safety_report_reactions srr on srr.safety_report_id = sr.safety_report_id
join reactions_dim r on r.id = srr.reaction_id
join safety_report_drugs srd on srd.safety_report_id = sr.safety_report_id
join drugs_dim d on d.id = srd.drug_id
where r.reaction_name ilike '%nausea%'
group by d.medicinal_product, d.generic_name, d.brand_name
order by report_count desc;
```

### Serious Hospitalization Reports by Year

```sql
select
    extract(year from received_date) as report_year,
    count(*) as hospitalization_count
from safety_reports
where seriousness_hospitalization = true
group by report_year
order by report_year;
```

### Report Details for a Specific Drug

```sql
select
    sr.safety_report_id,
    sr.received_date,
    sr.reporter_country,
    sr.serious,
    d.medicinal_product,
    srd.indication,
    srd.route
from safety_reports sr
join safety_report_drugs srd on srd.safety_report_id = sr.safety_report_id
join drugs_dim d on d.id = srd.drug_id
where d.medicinal_product ilike '%aspirin%'
order by sr.received_date desc;
```

## Example Workflow

1. Run `supabase_scripts.sql` in Supabase.
2. Add `SUPABASE_URL` and `SUPABASE_KEY` to `.env`.
3. Run `python app.py` to ingest a small sample.
4. Check the Supabase table editor to confirm rows were inserted.
5. Increase `run_pipeline(limit=...)` for larger ingestion.
6. Query normalized tables for dashboards or analysis.

## Notes and Limitations

- The script currently fetches only the first page using `skip=0`.
- Large ingestion jobs should add pagination by increasing `skip` across batches.
- `patients`, `safety_report_reactions`, and `safety_report_drugs` use insert operations, so rerunning the same reports can create duplicate child rows unless additional uniqueness constraints or upserts are added.
- Row Level Security is disabled in the SQL script for easier development. For production, enable RLS and add appropriate policies.
- OpenFDA fields are often missing or inconsistently populated, so the pipeline keeps raw JSON alongside normalized fields.
