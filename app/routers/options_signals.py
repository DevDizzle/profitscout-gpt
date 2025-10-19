import logging
from fastapi import APIRouter, HTTPException, Query, Response
from google.cloud import bigquery
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date

logger = logging.getLogger(__name__)
router = APIRouter()

# BigQuery Client
PROJECT_ID = "profitscout-lx6bb"
TABLE_ID = f"{PROJECT_ID}.profit_scout.options_analysis_signals"
client = bigquery.Client(project=PROJECT_ID)

# --- Helper Functions ---

def get_latest_run_date() -> str:
    """Fetches the most recent run_date from the BigQuery table."""
    query = f"SELECT MAX(run_date) as latest_date FROM `{TABLE_ID}`"
    try:
        query_job = client.query(query)
        results = query_job.result()
        row = next(results)
        latest_date = row.latest_date
        if isinstance(latest_date, date):
            return latest_date.strftime("%Y-%m-%d")
        else:
            # Fallback to yesterday if table is empty
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
    limit: int = 100,
    pageToken: Optional[str] = None,
):
    """
    Lists distinct tickers from the options signals dataset.
    - If `run_date` is not provided, it defaults to the most recent run.
    - Supports filtering by `ticker` (prefix search) and `option_type`.
    - Implements pagination using BigQuery's page tokens.
    """
    response.headers["Cache-Control"] = "public, max-age=300"
    
    effective_run_date = run_date if run_date else get_latest_run_date()
    
    query = f"""
        SELECT DISTINCT ticker
        FROM `{TABLE_ID}`
    """
    
    where_clauses = ["run_date = @run_date"]
    params = [bigquery.ScalarQueryParameter("run_date", "DATE", datetime.strptime(effective_run_date, "%Y-%m-%d").date())]
    
    if ticker:
        where_clauses.append("ticker LIKE @ticker")
        params.append(bigquery.ScalarQueryParameter("ticker", "STRING", f"{ticker.upper()}%" ))
        
    if option_type:
        where_clauses.append("option_type = @option_type")
        params.append(bigquery.ScalarQueryParameter("option_type", "STRING", option_type))
        
    query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY ticker"
    
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    
    try:
        iterator = client.query(
            query, job_config=job_config, page_size=limit, page_token=pageToken
        ).result()
        
        items = []
        for row in iterator:
            items.append({
                "id": row.ticker,
                "href": f"/v1/options-signals/{row.ticker}"
            })
            
        return {
            "dataset": "options-signals",
            "items": items,
            "nextPageToken": iterator.next_page_token,
        }
        
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
):
    """
    Retrieves the best-ranked options signals across all tickers for a given date.
    - `as_of`: 'latest' or a 'YYYY-MM-DD' date.
    - Ranking is based on setup quality, trend alignment, and IV favorability.
    """
    response.headers["Cache-Control"] = "public, max-age=300"
    
    run_date_str = get_latest_run_date() if as_of == "latest" else as_of
    
    query = f"""
        SELECT *
        FROM `{TABLE_ID}`
        WHERE run_date = @run_date
    """
    params = [bigquery.ScalarQueryParameter("run_date", "DATE", datetime.strptime(run_date_str, "%Y-%m-%d").date())]
    
    if option_type:
        query += " AND option_type = @option_type"
        params.append(bigquery.ScalarQueryParameter("option_type", "STRING", option_type))
        
    query += """
        ORDER BY
            CASE setup_quality_signal
                WHEN 'High' THEN 3
                WHEN 'Medium' THEN 2
                WHEN 'Low' THEN 1
                ELSE 0
            END DESC,
            is_trend_aligned DESC,
            is_iv_favorable DESC
        LIMIT @limit
    """
    params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
    
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    
    try:
        query_job = client.query(query, job_config=job_config)
        results = [map_row_to_dict(row) for row in query_job.result()]
        return {
            "dataset": "options-signals-top",
            "as_of": run_date_str,
            "items": results
        }
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
):
    """
    Resolves the best options trade signals for a specific ticker based on ranking criteria.
    - `as_of`: 'latest' or a 'YYYY-MM-DD' date.
    - `expiration_date`: If not provided, automatically selects one 30-45 days out.
    - `option_type`: 'CALL', 'PUT', or 'ANY'.
    - `top_n`: Number of signals to return.
    """
    response.headers["Cache-Control"] = "public, max-age=120"
    
    run_date_str = get_latest_run_date() if as_of == "latest" else as_of
    
    base_query = f" FROM `{TABLE_ID}` WHERE run_date = @run_date AND ticker = @ticker"
    params = [
        bigquery.ScalarQueryParameter("run_date", "DATE", datetime.strptime(run_date_str, "%Y-%m-%d").date()),
        bigquery.ScalarQueryParameter("ticker", "STRING", ticker.upper())
    ]
    
    if option_type != "ANY":
        base_query += " AND option_type = @option_type"
        params.append(bigquery.ScalarQueryParameter("option_type", "STRING", option_type))

    final_expiration_date = expiration_date
    if not final_expiration_date:
        # Find an optimal expiration date between 30 and 45 DTE
        dte_query = "SELECT expiration_date, days_to_expiration FROM " + base_query + \
                    " AND days_to_expiration BETWEEN 30 AND 45 ORDER BY days_to_expiration ASC LIMIT 1"
        
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        try:
            dte_job = client.query(dte_query, job_config=job_config)
            dte_results = list(dte_job.result())
            if dte_results:
                final_expiration_date = dte_results[0].expiration_date.isoformat()
            else:
                # Fallback: find the closest DTE if none are in the 30-45 range
                fallback_dte_query = "SELECT expiration_date, days_to_expiration FROM " + base_query + \
                                     " ORDER BY ABS(days_to_expiration - 37) ASC LIMIT 1"
                fallback_dte_job = client.query(fallback_dte_query, job_config=job_config)
                fallback_results = list(fallback_dte_job.result())
                if fallback_results:
                    final_expiration_date = fallback_results[0].expiration_date.isoformat()
                else:
                    raise HTTPException(status_code=404, detail=f"No options signals found for ticker {ticker.upper()} on {run_date_str}.")
        except Exception as e:
            logger.error(f"Error finding optimal expiration date for {ticker.upper()}: {e}")
            raise HTTPException(status_code=500, detail="Could not determine expiration date.")

    # Add expiration date to query
    base_query += " AND expiration_date = @expiration_date"
    params.append(bigquery.ScalarQueryParameter("expiration_date", "DATE", datetime.strptime(final_expiration_date, "%Y-%m-%d").date()))
    
    # Final query to get top signals
    ranking_query = "SELECT *" + base_query + """
        ORDER BY
            CASE setup_quality_signal
                WHEN 'High' THEN 3
                WHEN 'Medium' THEN 2
                WHEN 'Low' THEN 1
                ELSE 0
            END DESC,
            is_trend_aligned DESC,
            is_iv_favorable DESC
        LIMIT @top_n
    """
    params.append(bigquery.ScalarQueryParameter("top_n", "INT64", top_n))
    
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    
    try:
        query_job = client.query(ranking_query, job_config=job_config)
        results = [map_row_to_dict(row) for row in query_job.result()]
        
        if not results:
             raise HTTPException(status_code=404, detail=f"No options signals found for {ticker.upper()} on {run_date_str} with expiration {final_expiration_date}.")

        return {
            "dataset": "options-signals-item",
            "id": ticker.upper(),
            "as_of": run_date_str,
            "selected_expiration_date": final_expiration_date,
            "items": results
        }
    except HTTPException as e:
        raise e # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Error querying ticker signals for {ticker.upper()}: {e}")
        raise HTTPException(status_code=500, detail=f"Error querying BigQuery for ticker {ticker.upper()}: {e}")