
# ProfitScout Generic API

This API provides access to datasets stored in the `profit-scout-data` Google Cloud Storage bucket.

## Datasets

Datasets are represented by top-level folders in the GCS bucket. For example, the folder `recommendations` corresponds to the `recommendations` dataset.

### Dataset Naming

- Dataset names should be lowercase and contain only letters, numbers, and hyphens.
- Each dataset folder contains data for different symbols or entities.

## Manifests

To speed up the resolution of the "latest" version of an item, the API uses manifest files.

### Manifest Format

- Manifest files are stored in the `manifests` folder in the GCS bucket.
- The path to a manifest for a given item is `manifests/{dataset}/{id}.json`.
- The manifest is a JSON file with the following structure:

```json
{
  "latest_object": "recommendations/AAL_2025-10-15.md"
}
```

- `latest_object`: The full path to the latest object in the GCS bucket.

### Fallback Mechanism

If a manifest file is not found for a given item, the API will fall back to listing all objects for that item in the dataset folder and selecting the one that is lexicographically last, which is assumed to be the latest. This assumes a consistent naming convention for files, such as `{id}_{YYYY-MM-DD}.{ext}`.
