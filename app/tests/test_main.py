import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app, get_gcs_bucket
from app.routers.options_signals import get_bigquery_client

# Mock GCS and BigQuery clients
mock_gcs_bucket = MagicMock()
mock_bq_client = MagicMock()

def override_get_gcs_bucket():
    return mock_gcs_bucket

def override_get_bigquery_client():
    return mock_bq_client

app.dependency_overrides[get_gcs_bucket] = override_get_gcs_bucket
app.dependency_overrides[get_bigquery_client] = override_get_bigquery_client

@pytest.fixture
def client():
    # Reset mocks before each test
    mock_gcs_bucket.reset_mock()
    mock_bq_client.reset_mock()
    return TestClient(app)

def test_healthz(client):
    """Test the health check endpoint."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

def test_get_dataset_item_not_found(client):
    """Test the get_dataset_item endpoint when an item is not found."""
    mock_gcs_bucket.list_blobs.return_value = []
    response = client.get("/v1/recommendations/AAPL")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "Item not found."

@patch('app.routers.options_signals.get_latest_run_date', return_value="2024-01-01")
def test_list_options_signals(mock_get_latest_run_date, client):
    """Test the list_options_signals endpoint."""
    # Mock the return value for the main query
    mock_job_tickers = MagicMock()
    mock_job_tickers.result.return_value = iter([MagicMock(ticker='AAPL'), MagicMock(ticker='GOOG')])

    mock_bq_client.query.return_value = mock_job_tickers

    response = client.get("/v1/options-signals")
    assert response.status_code == 200
    assert response.json()["dataset"] == "options-signals"
    assert len(response.json()["items"]) == 2

def test_list_datasets(client):
    """Test the list_datasets endpoint."""
    mock_iterator = MagicMock()
    # To properly mock the pages, you need to make it an iterable of iterables
    type(mock_iterator).pages = [MagicMock(prefixes=['recommendations/', 'technicals/'])]
    mock_gcs_bucket.list_blobs.return_value = mock_iterator

    response = client.get("/v1")
    assert response.status_code == 200
    assert "recommendations" in response.json()["datasets"]
    assert "technicals" in response.json()["datasets"]
    assert "options-signals" in response.json()["datasets"]
