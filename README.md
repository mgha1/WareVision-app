# WareVision

WareVision is a FastAPI-based warehouse operations application with a browser UI for:

- live warehouse floor visibility
- slotting recommendations
- inbound inventory assignment
- demand forecasting and reorder signals
- warehouse analytics

The frontend is served by the backend from `warehouse_api/static`, so you start one service and open the app in the browser.

## Requisites

A new developer or operator needs:

- Python 3.9+
- Oracle wallet/config files for the target database
- valid Oracle credentials and DSN
- app login credentials and session secret
- Python dependencies from `requirements.txt`

## Project Structure

- `warehouse_api/main.py`: FastAPI app and API routes
- `warehouse_api/config.py`: environment-driven runtime settings
- `warehouse_api/database.py`: Oracle connection pool wrapper
- `warehouse_api/slotting.py`: slotting recommendation engine and scheduler
- `warehouse_api/forecast_engine.py`: forecasting and reorder-risk logic
- `warehouse_api/static/`: frontend HTML, CSS, and JavaScript
- `PROJECT_DOCUMENTATION.md`: business and feature documentation
- `warevision_architecture.jpg`: generated architecture diagram

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd WareVision-app
```

### 2. Create a virtual environment

```bash
python3.9 -m venv .venv
source .venv/bin/activate
```

If your machine uses a different Python binary, use that instead as long as it is Python 3.9 or later.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the sample file:

```bash
cp .env.example .env
```

Then set the values for your environment.

Required settings:

- `ORACLE_USER`
- `ORACLE_PASSWORD`
- `ORACLE_DSN`
- `ORACLE_CONFIG_DIR`
- `ORACLE_WALLET_DIR`
- `APP_USERNAME`
- `APP_PASSWORD`
- `SESSION_SECRET`

Optional settings:

- `ORACLE_POOL_MIN`
- `ORACLE_POOL_MAX`
- `SLOTTING_INTERVAL_SECONDS`
- `ENABLE_SLOTTING_SCHEDULER`
- `CORS_ORIGINS`

Example:

```env
ORACLE_USER=your_oracle_user
ORACLE_PASSWORD=your_oracle_password
ORACLE_DSN=your_oracle_dsn
ORACLE_CONFIG_DIR=/path/to/wallet
ORACLE_WALLET_DIR=/path/to/wallet
APP_USERNAME=admin
APP_PASSWORD=change-this-password
SESSION_SECRET=change-this-session-secret
SLOTTING_INTERVAL_SECONDS=60
ENABLE_SLOTTING_SCHEDULER=true
```

## Oracle Wallet Requirement

This project expects Oracle connectivity through `python-oracledb` using wallet/config-based connection settings.

You need the Oracle wallet files available locally, and the following settings must point to that location:

- `ORACLE_CONFIG_DIR`
- `ORACLE_WALLET_DIR`

If those paths are wrong or the wallet is missing, the app will fail during startup when it opens the Oracle connection pool.

## Run The Application

Start the backend:

```bash
python3.9 -m uvicorn warehouse_api.main:app --host 0.0.0.0 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/
```

For a remote server, replace `127.0.0.1` with the server IP or hostname.

## Default Behavior On Startup

On startup the app:

- opens the Oracle connection pool
- initializes support tables if needed
- prepares forecasting support data if needed
- starts the slotting scheduler if enabled

Because of that, database connectivity must be working before the app can serve requests successfully.

## Main Features

### Live Warehouse Map

- renders warehouse zones and slot positions
- shows occupancy and slot-level details
- overlays asset positions
- supports heatmap visualization

### Recommendation Queue

- generates slotting moves for high-frequency SKUs
- estimates travel savings
- allows operators to accept recommendations

### Inbound Inventory Workflow

- looks up SKUs
- recommends an available slot
- confirms assignment into inventory
- writes daily inbound movement records

### Forecasting

- uses recent movement/sales history
- predicts upcoming demand
- classifies SKUs into stockout, reorder, healthy, or slow-moving
- supports reorder initiation

### Analytics

- active SKUs
- total units
- occupancy
- asset counts
- queue savings
- inbound activity
- revenue and category mix

## Useful Files

- [README.md](/home/opc/myapp_v2/README.md)
- [PROJECT_DOCUMENTATION.md](/home/opc/myapp_v2/PROJECT_DOCUMENTATION.md)
- [warevision_architecture.jpg](/home/opc/myapp_v2/warevision_architecture.jpg)

## Common Clone-to-Run Checklist

After cloning, the minimum working sequence is:

1. Create and activate a virtual environment.
2. Install `requirements.txt`.
3. Copy `.env.example` to `.env` and fill in real values.
4. Put the Oracle wallet files on disk.
5. Start `uvicorn`.
6. Open port `8000` in the browser.


