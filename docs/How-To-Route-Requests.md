# How to Route Requests

This document outlines how to route different user intents to the appropriate API endpoints.

## Options Trading Intents

- **To get a list of tickers with options signals:**
  - **Endpoint:** `GET /v1/options-signals`
  - **Description:** Use this to get a list of all available tickers that have options signals for a given day.

- **To get the top signals for a specific ticker:**
  - **Endpoint:** `GET /v1/options-signals/{ticker}`
  - **Description:** Use this to retrieve the best-ranked options signals for a single ticker (e.g., TSLA). You can specify `as_of`, `option_type`, and `top_n`.

- **To get the top signals across all tickers:**
  - **Endpoint:** `GET /v1/options-signals/top`
  - **Description:** Use this to get the highest-rated signals across the entire market for a given day.
