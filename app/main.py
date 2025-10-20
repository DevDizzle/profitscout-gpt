from fastapi import FastAPI, HTTPException, Response, Depends
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

# --- GCS Client Dependency ---
BUCKET_NAME = "profit-scout-data"
DATE_REGEX = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})")

def get_gcs_bucket():
    """Provides a GCS bucket object, allowing for dependency injection."""
    try:
        storage_client = storage.Client()
        return storage_client.bucket(BUCKET_NAME)
    except Exception as e:
        logger.error(f"Failed to create GCS client: {e}")
        raise HTTPException(status_code=500, detail="Could not connect to Google Cloud Storage.")

# --- Helper Functions ---

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
    return policy.get(dataset, [".json", ".md", ".txt"])

def find_best_artifact(dataset: str, item_id: str, as_of: str, bucket: storage.Bucket) -> Optional[storage.Blob]:
    """Finds the best artifact in GCS based on dataset, ID, and date."""
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

    artifacts = []
    preferred_exts = get_preferred_extensions(dataset)
    for blob in candidate_blobs:
        ext = next((ext for ext in preferred_exts if blob.name.endswith(ext)), None)
        if not ext:
            continue
        date_match = DATE_REGEX.search(blob.name)
        parsed_date = date_match.group(1) if date_match else None
        artifacts.append({"blob": blob, "date": parsed_date, "ext_preference": preferred_exts.index(ext)})

    if not artifacts:
        return None

    artifacts.sort(key=lambda x: (x["date"] or "", x["ext_preference"], x["blob"].updated), reverse=True)

    if as_of == "latest":
        return artifacts[0]["blob"]
    else:
        for artifact in artifacts:
            if artifact["date"] == as_of:
                return artifact["blob"]
    return None

# --- Endpoints ---

@app.get("/v1/{dataset}/{id}", summary="Get a specific item from a dataset")
def get_dataset_item(
    dataset: str, id: str, response: Response, as_of: str = "latest", bucket: storage.Bucket = Depends(get_gcs_bucket)
):
    response.headers["Cache-Control"] = "public, max-age=120"
    blob = find_best_artifact(dataset, id, as_of, bucket)

    if not blob:
        raise HTTPException(status_code=404, detail={"error": "Item not found.", "hint": f"No {dataset} artifact for ID={id.upper()} (as_of={as_of})."})

    date_match = DATE_REGEX.search(blob.name)
    as_of_date_str = date_match.group(1) if date_match else blob.updated.strftime("%Y-%m-%d")
    as_of_datetime = datetime.strptime(as_of_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

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
    if blob.name.endswith((".md", ".txt")):
        envelope["summary_md"] = content
    elif blob.name.endswith(".json"):
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                envelope["summary_md"] = data.pop("analysis", data.pop("summary_md", None))
                envelope["metrics"] = data
            else:
                envelope["metrics"] = data
        except json.JSONDecodeError:
            logger.warning(f"Could not parse JSON for {blob.name}, returning as text.")
            envelope["summary_md"] = content
    return envelope

@app.get("/v1", summary="List available datasets")
def list_datasets(response: Response, bucket: storage.Bucket = Depends(get_gcs_bucket)):
    response.headers["Cache-Control"] = "public, max-age=300"
    try:
        iterator = bucket.list_blobs(prefix='', delimiter='/')
        prefixes = set(p for page in iterator.pages for p in page.prefixes)
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
