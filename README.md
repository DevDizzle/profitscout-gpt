# ProfitScout API

Python-based **FastAPI** backend for the ProfitScout GPT. This API serves AI-driven financial research, pulling stock and options-trading data from **Google Cloud Storage (GCS)** and **BigQuery**.

---

## API Overview

This API serves financial data from two primary sources:

- **Google Cloud Storage (GCS):** Provides access to file-based datasets (e.g., `.md`, `.json`) stored in the `profit-scout-data` bucket. Used for datasets like **recommendations**, **technicals**, and **news-analysis**.
- **Google BigQuery:** Powers “virtual datasets” that are queried live. The primary example is the **options-signals** dataset, which queries the `options_analysis_signals` table in BigQuery.

---

## Available Endpoints

### General

- `GET /v1`  
  **Summary:** List all available datasets from both GCS and BigQuery.

### GCS Datasets

- `GET /v1/{dataset}/{id}`  
  **Summary:** Get a specific item from a GCS dataset (e.g., get recommendations for `AAPL`).  
  **Parameters:**  
  - `as_of`: A date (`YYYY-MM-DD`) or `'latest'` (default).

### Options Signals (BigQuery)

- `GET /v1/options-signals`  
  **Summary:** List distinct tickers that have available options signals.

- `GET /v1/options-signals/top`  
  **Summary:** Get the top-ranked options signals across all tickers for a given day.

- `GET /v1/options-signals/{ticker}`  
  **Summary:** Get the top-ranked options signals for a specific ticker.

---

## GCS Datasets

- Datasets are represented by top-level folders in the `profit-scout-data` GCS bucket.  
  For example, the folder `recommendations` corresponds to the **recommendations** dataset.

### Dataset Naming

- Dataset names should be **lowercase** and contain only **letters**, **numbers**, and **hyphens**.
- Each dataset folder contains data for different symbols or entities.

---

## GCS Manifests

To speed up the resolution of the `"latest"` version of an item, the API **used to** use manifest files.

> **Note:** The current implementation in `app/main.py` appears to use a fallback mechanism by default—listing blobs and sorting them to find the best artifact—rather than relying on manifests. This section is kept for historical context.

### Manifest Format

- Manifest files are stored in the `manifests` folder in the GCS bucket.
- The path to a manifest for a given item is:  
  `manifests/{dataset}/{id}.json`

**Example:**
```json
{
  "latest_object": "recommendations/AAL_2025-10-15.md"
}
latest_object: The full path to the latest object in the GCS bucket.

```

### Fallback Mechanism (Current)
The API lists all objects for an item in the dataset folder (e.g., recommendations/AAPL*) and selects the best one based on:

The as_of date (if provided),

Preferred file extensions,

Object update time.

This assumes a consistent naming convention for files such as:
{id}_{YYYY-MM-DD}.{ext}

### License
This project is licensed under the MIT License.
