from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import storage
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import json
import logging
import re
from app.routers import options_signals

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ProfitScout Generic API", version="1.4.0")

# Include routers
app.include_router(options_signals.router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# GCS Client
storage_client = storage.Client()
BUCKET_NAME = "profit-scout-data"

# Regex to find a date in a filename
DATE_REGEX = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})")

def get_gcs_bucket():
    return storage_client.bucket(BUCKET_NAME)

def get_preferred_extensions(dataset: str) -> List[str]:
    """Returns a list of preferred file extensions for a given dataset."""
    policy = {
        "recommendations": [".md", ".json"],
        "business-summaries": [".md", ".json"],
        "technicals": [".json"],
        "technicals-analysis": [".json"],
        "news-analysis": [".json"],
        "earnings-call-transcripts": [".md", ".txt"],
        "transcript-analysis": [".md", ".json"],
        "mda-analysis": [".md", ".json"],
        "financials-analysis": [".md", ".json"],
        "fundamentals-analysis": [".md", ".json"],
        "financial-statements": [".json"],
        "key-metrics": [".json"],
        "ratios": [".json"],
        "headline-news": [".json"],
        "prices": [".json"],
        "price-chart-json": [".json"],
        "sec-business": [".md", ".txt"],
        "sec-mda": [".md", ".txt"],
        "sec-risk": [".md", ".txt"],
    }
    return policy.get(dataset, [".json", ".md", ".txt"]) # Default order

def find_best_artifact(dataset: str, item_id: str, as_of: str) -> Optional[storage.Blob]:
    """Finds the best artifact in GCS based on dataset, ID, and date."""
    bucket = get_gcs_bucket()
    item_id_upper = item_id.upper()
    
    datasets_to_try = [dataset]
    if dataset == "key-levels":
        datasets_to_try = ["technicals-analysis", "technicals"]

    candidate_blobs = []
    for ds in datasets_to_try:
        prefix = f"{ds}/{item_id_upper}"
        logger.info(f"Searching for blobs with prefix: {prefix}")
        blobs = list(bucket.list_blobs(prefix=prefix))
        candidate_blobs.extend(blobs)

    if not candidate_blobs:
        return None

    # Filter by preferred extensions and parse dates
    artifacts = []
    preferred_exts = get_preferred_extensions(dataset)
    for blob in candidate_blobs:
        ext = next((ext for ext in preferred_exts if blob.name.endswith(ext)), None)
        if not ext:
            continue

        date_match = DATE_REGEX.search(blob.name)
        parsed_date = date_match.group(1) if date_match else None
        artifacts.append({
            "blob": blob,
            "date": parsed_date,
            "ext_preference": preferred_exts.index(ext)
        })

    if not artifacts:
        return None

    # Sort candidates: by date, then extension preference, then updated time
    artifacts.sort(key=lambda x: (x["date"] or "", x["ext_preference"], x["blob"].updated), reverse=True)

    if as_of == "latest":
        return artifacts[0]["blob"]
    else: # as_of is a specific date
        for artifact in artifacts:
            if artifact["date"] == as_of:
                return artifact["blob"]

    return None

@app.get("/v1/{dataset}/{id}", summary="Get a specific item from a dataset")
def get_dataset_item(dataset: str, id: str, response: Response, as_of: str = "latest"):
    """Retrieves a single, best-matching item from a dataset."""
    response.headers["Cache-Control"] = "public, max-age=120"
    
    blob = find_best_artifact(dataset, id, as_of)

    if not blob:
        raise HTTPException(status_code=404, detail={
            "error": "Item not found.",
            "hint": f"No {dataset} artifact for ID={id.upper()} (as_of={as_of})."
        })

    # Determine the as_of date for the response
    date_match = DATE_REGEX.search(blob.name)
    if date_match:
        as_of_date_str = date_match.group(1)
    else:
        as_of_date_str = blob.updated.strftime("%Y-%m-%d")
    as_of_datetime = datetime.strptime(as_of_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    # Prepare the base response envelope
    envelope = {
        "dataset": dataset,
        "id": id.upper(),
        "as_of": as_of_datetime.strftime("%Y-%m-%dT00:00:00Z"),
        "summary_md": None,
        "artifact_url": blob.public_url,
        "source": "ProfitScout",
        "disclaimer": "Educational only; not investment advice.",
    }

    content = blob.download_as_string().decode('utf-8')

    if blob.name.endswith(".md") or blob.name.endswith(".txt"):
        envelope["summary_md"] = content
    elif blob.name.endswith(".json"):
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                if "analysis" in data:
                    envelope["summary_md"] = data.pop("analysis")
                if "summary_md" in data:
                    envelope["summary_md"] = data.pop("summary_md")
                envelope["metrics"] = data
            else:
                envelope["metrics"] = data # Handle JSON arrays
        except json.JSONDecodeError:
            logger.warning(f"Could not parse JSON for {blob.name}, returning as text.")
            envelope["summary_md"] = content

    return envelope

# Keep other endpoints as they are
@app.get("/v1", summary="List available datasets")
def list_datasets(response: Response):
    response.headers["Cache-Control"] = "public, max-age=300"
    try:
        bucket = get_gcs_bucket()
        iterator = bucket.list_blobs(prefix='', delimiter='/')
        prefixes = set()
        for page in iterator.pages:
            prefixes.update(page.prefixes)
        datasets = sorted([p.strip('/') for p in prefixes if p.strip('/') != 'manifests'])
        datasets.append("options-signals")
        if not datasets:
            return {"datasets": ["recommendations", "key-levels", "technicals", "options-signals"], "hint": "fallback"}
        return {"datasets": sorted(datasets)}
    except Exception as e:
        logger.error(f"Error listing datasets: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve datasets.")

@app.get("/healthz")
def healthz():
    return {"ok": True}