import logging
from fastapi import APIRouter, HTTPException, Query, Response, Depends
from google.cloud import bigquery
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date

logger = logging.getLogger(__name__)
router = APIRouter()

# --- BigQuery Client Dependency ---
PROJECT_ID = "profitscout-lx6bb"
TABLE_ID = f"{PROJECT_ID}.profit_scout.options_analysis_signals"

def get_bigquery_client():
    """Provides a BigQuery client, allowing for dependency injection and easier testing."""
    try:
        return bigquery.Client(project=PROJECT_ID)
    except Exception as e:
        logger.error(f"Failed to create BigQuery client: {e}")
        raise HTTPException(status_code=500, detail="Could not connect to BigQuery.")

# --- Helper Functions ---

def get_latest_run_date(client: bigquery.Client) -> str:
    """Fetches the most recent run_date from the BigQuery table."""
    query = f"SELECT MAX(run_date) as latest_date FROM `{TABLE_ID}`"
    try:
        query_job = client.query(query)
        results = query_job.result()
        row = next(results)
        latest_date = row.latest_date
        if latest_date:
            return latest_date
        else:
            return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception as e:
        logger.error(f"Could not fetch latest run date: {e}")
        raise HTTPException(status_code=500, detail="Could not fetch latest run date from BigQuery.")

def map_row_to_dict(row: bigquery.Row) -> Dict[str, Any]:
    """Converts a BigQuery Row to a dictionary, handling date/datetime objects."""
    row_dict = dict(row.items())
    for key, value in row_dict.items():
        if isinstance(value, (datetime, date)):
            row_dict[key] = value.isoformat()
    return row_dict

# --- Endpoints ---

@router.get(
    "/v1/options-signals",
    summary="List distinct tickers for options signals",
    tags=["options-signals"],
)
def list_options_signals(
    response: Response,
    run_date: Optional[str] = None,
    ticker: Optional[str] = None,
    option_type: Optional[str] = Query(None, enum=["CALL", "PUT"]),
    client: bigquery.Client = Depends(get_bigquery_client),
):
    response.headers["Cache-Control"] = "public, max-age=300"
    effective_run_date = run_date if run_date else get_latest_run_date(client)
    
    query = f"SELECT DISTINCT ticker FROM `{TABLE_ID}`"
    where_clauses = ["run_date = @run_date"]
    params = [bigquery.ScalarQueryParameter("run_date", "STRING", effective_run_date)]
    
    if ticker:
        where_clauses.append("ticker LIKE @ticker")
        params.append(bigquery.ScalarQueryParameter("ticker", "STRING", f"{ticker.upper()}%"))
    if option_type:
        where_clauses.append("option_type = @option_type")
        params.append(bigquery.ScalarQueryParameter("option_type", "STRING", option_type))
        
    query += " WHERE " + " AND ".join(where_clauses) + " ORDER BY ticker"
    
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    try:
        iterator = client.query(query, job_config=job_config).result()
        items = [{"id": row.ticker, "href": f"/v1/options-signals/{row.ticker}"} for row in iterator]
        return {"dataset": "options-signals", "items": items}
    except Exception as e:
        logger.error(f"Error querying options signals tickers: {e}")
        raise HTTPException(status_code=500, detail=f"Error querying BigQuery for distinct tickers: {e}")

@router.get(
    "/v1/options-signals/top",
    summary="Get top-ranked options signals across all tickers",
    tags=["options-signals"],
)
def get_top_options_signals(
    response: Response,
    as_of: str = "latest",
    option_type: Optional[str] = Query(None, enum=["CALL", "PUT"]),
    limit: int = 10,
    client: bigquery.Client = Depends(get_bigquery_client),
):
    response.headers["Cache-Control"] = "public, max-age=300"
    run_date_str = get_latest_run_date(client) if as_of == "latest" else as_of
    
    query = f"SELECT * FROM `{TABLE_ID}` WHERE run_date = @run_date"
    params = [bigquery.ScalarQueryParameter("run_date", "STRING", run_date_str)]
    
    if option_type:
        query += " AND option_type = @option_type"
        params.append(bigquery.ScalarQueryParameter("option_type", "STRING", option_type))
        
    query += """
        ORDER BY
            CASE setup_quality_signal WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 1 ELSE 0 END DESC,
            CASE stock_price_trend_signal WHEN 'Aligned' THEN 1 ELSE 0 END DESC,
            CASE volatility_comparison_signal WHEN 'Favorable' THEN 1 ELSE 0 END DESC
        LIMIT @limit
    """
    params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
    
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    try:
        query_job = client.query(query, job_config=job_config)
        results = [map_row_to_dict(row) for row in query_job.result()]
        return {"dataset": "options-signals-top", "as_of": run_date_str, "items": results}
    except Exception as e:
        logger.error(f"Error querying top options signals: {e}")
        raise HTTPException(status_code=500, detail=f"Error querying BigQuery for top signals: {e}")

@router.get(
    "/v1/options-signals/{ticker}",
    summary="Get top options signals for a specific ticker",
    tags=["options-signals"],
)
def get_ticker_options_signals(
    ticker: str,
    response: Response,
    as_of: str = "latest",
    expiration_date: Optional[str] = None,
    option_type: str = Query("ANY", enum=["CALL", "PUT", "ANY"]),
    top_n: int = Query(3, alias="top_n"),
    client: bigquery.Client = Depends(get_bigquery_client),
):
    response.headers["Cache-Control"] = "public, max-age=120"
    run_date_str = get_latest_run_date(client) if as_of == "latest" else as_of
    
    base_query = f" FROM `{TABLE_ID}` WHERE run_date = @run_date AND ticker = @ticker"
    params = [
        bigquery.ScalarQueryParameter("run_date", "STRING", run_date_str),
        bigquery.ScalarQueryParameter("ticker", "STRING", ticker.upper())
    ]
    
    if option_type != "ANY":
        base_query += " AND option_type = @option_type"
        params.append(bigquery.ScalarQueryParameter("option_type", "STRING", option_type))

    final_expiration_date = expiration_date
    if not final_expiration_date:
        dte_query = "SELECT expiration_date FROM " + base_query + \
                    " AND days_to_expiration BETWEEN 30 AND 45 ORDER BY days_to_expiration ASC LIMIT 1"
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        try:
            dte_results = list(client.query(dte_query, job_config=job_config).result())
            if dte_results:
                final_expiration_date = dte_results[0].expiration_date.isoformat()
            else:
                fallback_dte_query = "SELECT expiration_date FROM " + base_query + \
                                     " ORDER BY ABS(days_to_expiration - 37) ASC LIMIT 1"
                fallback_results = list(client.query(fallback_dte_query, job_config=job_config).result())
                if fallback_results:
                    final_expiration_date = fallback_results[0].expiration_date.isoformat()
                else:
                    raise HTTPException(status_code=404, detail=f"No options signals found for ticker {ticker.upper()} on {run_date_str}.")
        except Exception as e:
            logger.error(f"Error finding optimal expiration date for {ticker.upper()}: {e}")
            raise HTTPException(status_code=500, detail="Could not determine expiration date.")

    base_query += " AND expiration_date = @expiration_date"
    params.append(bigquery.ScalarQueryParameter("expiration_date", "STRING", final_expiration_date))
    
    ranking_query = "SELECT *" + base_query + """
        ORDER BY
            CASE setup_quality_signal WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 1 ELSE 0 END DESC,
            CASE stock_price_trend_signal WHEN 'Aligned' THEN 1 ELSE 0 END DESC,
            CASE volatility_comparison_signal WHEN 'Favorable' THEN 1 ELSE 0 END DESC
        LIMIT @top_n
    """
    params.append(bigquery.ScalarQueryParameter("top_n", "INT64", top_n))
    
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    try:
        query_job = client.query(ranking_query, job_config=job_config)
        results = [map_row_to_dict(row) for row in query_job.result()]
        if not results:
            raise HTTPException(status_code=404, detail=f"No options signals found for {ticker.upper()} on {run_date_str} with expiration {final_expiration_date}.")
        return {"dataset": "options-signals-item", "id": ticker.upper(), "as_of": run_date_str, "selected_expiration_date": final_expiration_date, "items": results}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error querying ticker signals for {ticker.upper()}: {e}")
        raise HTTPException(status_code=500, detail=f"Error querying BigQuery for ticker {ticker.upper()}: {e}")
