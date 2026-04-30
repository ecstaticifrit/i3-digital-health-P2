import requests
import uuid
import time
from datetime import datetime
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

API_URL = "https://api.fda.gov/drug/event.json"

# ----------------------------
# Helpers
# ----------------------------

def parse_date(date_str):
    try:
        if not date_str:
            return None
        return datetime.strptime(date_str, "%Y%m%d").date().isoformat()
    except:
        return None


def safe_bool(val):
    return True if val == "1" else False


def get_openfda_field(openfda, key):
    if not openfda:
        return None
    val = openfda.get(key)
    return val[0] if isinstance(val, list) and val else None


# ----------------------------
# Fetch Data
# ----------------------------


def fetch_data(limit, skip=0, retries=5):
    params = {
        "search": "receivedate:[20040101 TO 20081231]",
        "limit": limit,
        "skip": skip
    }

    for attempt in range(retries):
        try:
            res = requests.get(API_URL, params=params, timeout=10)

            if res.status_code == 200:
                return res.json()["results"]

            elif res.status_code >= 500:
                print(f"⚠️ Server error {res.status_code}, retrying...")

        except requests.exceptions.RequestException as e:
            print(f"⚠️ Request failed: {e}")

        time.sleep(2 ** attempt)  # exponential backoff

    raise Exception("❌ Failed after retries")


# ----------------------------
# Insert Functions
# ----------------------------

def insert_raw(report):
    supabase.table("fda_raw_events").upsert({
        "safety_report_id": report.get("safetyreportid"),
        "payload": report
    }).execute()


def insert_safety_report(report):
    data = {
        "safety_report_id": report.get("safetyreportid"),
        "received_date": parse_date(report.get("receivedate")),
        "receipt_date": parse_date(report.get("receiptdate")),
        "transmission_date": parse_date(report.get("transmissiondate")),

        "serious": safe_bool(report.get("serious")),
        "seriousness_death": safe_bool(report.get("seriousnessdeath")),
        "seriousness_life_threatening": safe_bool(report.get("seriousnesslifethreatening")),
        "seriousness_hospitalization": safe_bool(report.get("seriousnesshospitalization")),

        "company_number": report.get("companynumb"),
        "reporter_country": (report.get("primarysource") or {}).get("reportercountry"),

        "meta": report
    }

    supabase.table("safety_reports").upsert(data).execute()


def insert_patient(report):
    patient = report.get("patient")
    if not patient:
        return

    data = {
        "id": str(uuid.uuid4()),
        "safety_report_id": report.get("safetyreportid"),
        "age": patient.get("patientonsetage"),
        "age_unit": patient.get("patientonsetageunit"),
        "sex": patient.get("patientsex"),
        "death_date": parse_date((patient.get("patientdeath") or {}).get("patientdeathdate")),
        "raw": patient
    }

    supabase.table("patients").insert(data).execute()


def get_or_create_reaction(reaction_name):
    res = supabase.table("reactions_dim").select("id").eq("reaction_name", reaction_name).execute()
    
    if res.data:
        return res.data[0]["id"]

    insert = supabase.table("reactions_dim").insert({
        "reaction_name": reaction_name
    }).execute()

    return insert.data[0]["id"]


def insert_reactions(report):
    patient = report.get("patient") or {}
    reactions = patient.get("reaction", [])

    for r in reactions:
        name = r.get("reactionmeddrapt")
        if not name:
            continue

        reaction_id = get_or_create_reaction(name)

        supabase.table("safety_report_reactions").insert({
            "id": str(uuid.uuid4()),
            "safety_report_id": report.get("safetyreportid"),
            "reaction_id": reaction_id
        }).execute()


def get_or_create_drug(drug):
    openfda = drug.get("openfda", {})

    medicinal_product = drug.get("medicinalproduct")
    generic_name = get_openfda_field(openfda, "generic_name")
    brand_name = get_openfda_field(openfda, "brand_name")

    res = supabase.table("drugs_dim") \
        .select("id") \
        .eq("medicinal_product", medicinal_product) \
        .execute()

    if res.data:
        return res.data[0]["id"]

    insert = supabase.table("drugs_dim").insert({
        "id": str(uuid.uuid4()),
        "medicinal_product": medicinal_product,
        "generic_name": generic_name,
        "brand_name": brand_name,
        "manufacturer_name": get_openfda_field(openfda, "manufacturer_name"),
        "substance_name": get_openfda_field(openfda, "substance_name"),
        "openfda": openfda
    }).execute()

    return insert.data[0]["id"]


def insert_drugs(report):
    patient = report.get("patient") or {}
    drugs = patient.get("drug", [])

    for d in drugs:
        drug_id = get_or_create_drug(d)

        data = {
            "id": str(uuid.uuid4()),
            "safety_report_id": report.get("safetyreportid"),
            "drug_id": drug_id,

            "drug_characterization": d.get("drugcharacterization"),
            "authorization_number": d.get("drugauthorizationnumb"),
            "route": d.get("drugadministrationroute"),
            "indication": d.get("drugindication"),

            "start_date": parse_date(d.get("drugstartdate")),
            "end_date": parse_date(d.get("drugenddate")),
            "treatment_duration": d.get("drugtreatmentduration"),
            "treatment_duration_unit": d.get("drugtreatmentdurationunit"),

            "raw": d
        }

        supabase.table("safety_report_drugs").insert(data).execute()


# ----------------------------
# Main Pipeline
# ----------------------------

def run_pipeline(limit):
    reports = fetch_data(limit, 0, 5)

    for report in reports:
        try:
            insert_raw(report)
            insert_safety_report(report)
            insert_patient(report)
            insert_reactions(report)
            insert_drugs(report)

            print(f"✅ Processed {report.get('safetyreportid')}")

        except Exception as e:
            print(f"❌ Error for {report.get('safetyreportid')}: {e}")


if __name__ == "__main__":
    run_pipeline(limit=5)