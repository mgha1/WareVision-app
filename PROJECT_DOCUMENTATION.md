# WareVision Project Documentation

## 1. Executive Summary

WareVision is a warehouse operations control-room application built as a FastAPI backend with a single-page frontend. It combines live warehouse visibility, operator-guided slotting decisions, inbound inventory assignment, and demand forecasting into one system backed by Oracle data.

The application is designed for distribution centers, 3PL operators, retail warehouses, and manufacturing stores operations that need better slot utilization, faster pick paths, fewer stockouts, and clearer floor-level operational decisions.

## 2. Product Positioning

### What problem this app solves

Warehouse teams often have data spread across multiple tools:

- floor layout and slot occupancy in one place
- inbound receiving decisions in another
- replenishment and stockout planning in another
- movement recommendations based on tribal knowledge rather than data

WareVision consolidates those workflows into a single operator-facing application.

### Industry / business solution

This is a warehouse intelligence and slotting optimization solution for intralogistics and supply chain operations. It addresses:

- warehouse slot optimization
- fast-pick zone utilization
- receiving putaway assistance
- live floor monitoring
- labor travel reduction
- replenishment forecasting
- operator workflow visibility

### Business value

- Reduces picker and forklift travel by moving high-frequency SKUs closer to dispatch.
- Improves receiving speed by recommending the best available slot for inbound inventory.
- Lowers stockout risk by surfacing reorder candidates before inventory runs out.
- Increases warehouse throughput by exposing occupancy, queue, asset, and activity metrics in one interface.
- Creates more consistent operator decisions because recommendations are data-backed instead of ad hoc.
- Improves leadership reporting through real-time operational analytics and daily activity summaries.

## 3. Technical Overview

### Stack

- Backend: FastAPI
- Frontend: static HTML/CSS/JavaScript SPA
- Database: Oracle via `python-oracledb` connection pooling
- Scheduler: APScheduler background job
- Forecasting: NumPy + scikit-learn linear regression
- Auth: session-based login using Starlette session middleware

### Runtime architecture

1. The browser loads `index.html` from FastAPI.
2. The SPA authenticates against `/api/login`.
3. After login, the frontend pulls analytics, floor, asset, recommendation, inbound, and forecast data from FastAPI JSON endpoints.
4. FastAPI reads and writes warehouse state in Oracle tables such as `inventory`, `slots`, `warehouse_zones`, `asset_positions`, `movement_log`, and `slotting_recommendations`.
5. A background slotting scheduler periodically analyzes current inventory positions and inserts new slotting recommendations.
6. The forecast engine reads historical sales/pick data, builds demand forecasts, and classifies SKUs by replenishment risk.

### Important backend behaviors

- The app opens the Oracle connection pool on startup.
- The app auto-provisions support tables like `slot_assignments`, `movement_log`, and `forecast_history` if missing.
- Several endpoints are cached briefly for fast UI refreshes.
- Authentication is required for all operational APIs except session/login metrics/login/logout.

## 4. Main Product Features

### 4.1 Login and Operator Access

Operators sign in through a branded login screen that also surfaces live top-level warehouse metrics such as total slots, fast-pick utilization, queue savings, and zone count.

What it does:

- authenticates users through `/api/login`
- persists authenticated state in a server-side session
- exposes `/api/session` for SPA bootstrapping
- supports `/api/logout`

Business value:

- gives operators a single controlled entry point
- allows the application to gate all warehouse actions behind authenticated sessions

### 4.2 Analytics Dashboard

The analytics view is the operational summary page for the warehouse.

It shows:

- active SKUs
- total units on hand
- occupancy rate
- active tracked assets
- pending recommendation queue
- queue savings in meters
- inbound units received today
- revenue recognized today
- capacity by warehouse zone
- asset status distribution
- recommendation status distribution
- inbound activity by hour
- sales trend
- top picked SKUs
- category mix

How it works:

- `/api/analytics` aggregates multiple Oracle queries into a single dashboard payload
- the frontend refreshes and renders compact visual cards, lists, and tables

Business value:

- gives supervisors a fast view of warehouse health
- highlights operational bottlenecks without needing separate reports
- ties floor operations to business outcomes like revenue and throughput

### 4.3 Live Warehouse Map

The live map visualizes warehouse zones and individual slots.

It includes:

- zone geometry and slot geometry from Oracle
- occupied vs empty slot states
- congestion highlighting based on pick count
- forklift / worker asset overlays
- slot hover and selection details
- selected-slot recommendation details
- system status banner

How it works:

- `/api/floor` returns zones and slots
- `/api/assets` returns live asset positions
- `/api/heatmap` returns utilization overlays by zone
- the frontend draws the map in the browser and updates it on a timer

Business value:

- gives floor teams a shared operational picture
- reduces time spent manually checking slot status
- supports faster exception handling during active operations

### 4.4 Heatmap Overlay

Operators can switch on a heatmap overlay to understand zone pressure.

What it highlights:

- total slots per zone
- occupied slots per zone
- occupancy ratio / zone load

Business value:

- makes congestion and space pressure obvious
- helps supervisors decide where to rebalance work or inventory

### 4.5 AI-style Slotting Recommendation Queue

The recommendation rail displays pending slotting moves generated by the backend scheduler.

Each recommendation contains:

- SKU
- current slot
- proposed destination slot
- estimated savings in meters
- a generated reason string explaining the move
- current recommendation status

How recommendations are generated:

- the scheduler analyzes current inventory positions
- it calculates pick frequency over the last 30 days
- it measures current distance from each SKU’s slot to the dispatch area
- it finds available fast-pick slots
- it assigns the highest-waste SKUs to the nearest empty fast-pick locations
- it stores the move in `slotting_recommendations`

How operators use it:

- the queue loads through `/api/recommendations`
- operators accept a move through `/api/accept-recommendation`
- acceptance moves inventory, marks the chosen recommendation `ACCEPTED`, and supersedes conflicting pending moves

Business value:

- shortens travel distance for high-frequency SKUs
- improves pick speed and labor efficiency
- introduces a repeatable slotting discipline instead of relying on operator intuition

### 4.6 Manual Inventory Movement

The backend also supports direct inventory movement between slots.

What it does:

- validates source inventory
- validates destination slot existence
- blocks moves into occupied slots
- updates inventory and slot occupancy state

Endpoint:

- `/api/move-inventory`

Business value:

- supports exception handling and operator overrides
- allows operations staff to correct slot placement without waiting for automation

### 4.7 Inbound Inventory Recommendation and Assignment

The inbound workflow helps receiving staff decide where to place newly arrived inventory.

Operator workflow:

1. Enter SKU, quantity, category, supplier, notes, and optional weight.
2. Request a recommended slot.
3. Review the recommended slot, zone, distance to dispatch, zone occupancy, and estimated travel savings.
4. Confirm assignment.
5. Review the new record in today’s inbound log.

How slot recommendation works:

- the app checks whether the SKU already exists
- it computes recent pick frequency
- hot SKUs are routed toward fast-pick
- lower-frequency SKUs are routed toward bulk storage
- it finds the nearest available slot in the target zone
- it estimates savings based on average available distance vs chosen slot distance

Key endpoints:

- `/api/skus/{sku_id}`
- `/api/inventory/recommend`
- `/api/inventory/assign`
- `/api/inventory/today`

Business value:

- improves putaway consistency
- reduces time spent deciding where inbound stock belongs
- aligns receiving decisions with downstream picking efficiency
- creates a movement log for operational traceability

### 4.8 Today’s Inbound Log

The inbound log is a same-day operational trace of assigned inbound inventory.

It records:

- timestamp
- SKU
- SKU name
- quantity
- assigned slot
- zone
- status

Business value:

- gives receiving supervisors a live operational ledger
- helps audit what was assigned, where, and when

### 4.9 Demand Forecasting and Replenishment Control

The forecasting view turns historical movement into forward-looking replenishment guidance.

It includes:

- 7, 14, and 30 day forecast horizons
- searchable SKU table
- status classification badges
- per-SKU historical vs forecast chart
- reorder queue
- reorder action trigger

Forecast logic:

- uses up to 90 days of demand history
- fills missing days in the history
- smooths demand with a rolling average
- fits a linear regression model
- predicts future demand with lower and upper bounds
- estimates average daily demand and forecast total
- computes days until stockout and suggested reorder quantity

Status classes:

- `stockout_risk`
- `reorder_now`
- `healthy`
- `slow_moving`
- `ordered` after a reorder signal is raised

Key endpoints:

- `/api/forecast/summary`
- `/api/forecast/sku/{sku_id}`
- `/api/forecast/reorder-queue`
- `/api/forecast/reorder/{sku_id}`

Business value:

- reduces stockouts
- supports proactive replenishment
- turns warehouse movement data into inventory planning decisions
- gives operators and planners a common view of demand risk

### 4.10 Auto-generated Forecast History Support

If `forecast_history` is missing, the app creates it and seeds it using available sales and pick history, including synthetic fill-in data where required.

Business value:

- lowers implementation friction in demo or pilot environments
- lets forecasting work even when historical data is incomplete

### 4.11 Scheduled Background Slotting Analysis

On startup, the app can launch a scheduler that reruns slotting analysis on a fixed interval.

Default configuration:

- enabled by default
- interval controlled by `SLOTTING_INTERVAL_SECONDS`

Business value:

- keeps the recommendation queue fresh without operator intervention
- supports near-real-time optimization as floor state changes

## 5. API Surface

### Authentication and session

- `GET /api/session`: current authenticated session state
- `POST /api/login`: log in
- `POST /api/logout`: log out
- `GET /api/login-metrics`: public login-screen warehouse summary

### Floor operations

- `GET /api/floor`: warehouse zones and slots
- `GET /api/inventory`: raw inventory listing
- `GET /api/assets`: active asset positions
- `GET /api/heatmap`: occupancy overlays
- `POST /api/move-inventory`: move SKU from one slot to another

### Slotting recommendations

- `GET /api/recommendations`: pending recommendation queue
- `POST /api/accept-recommendation`: accept a recommended move

### Inbound receiving

- `GET /api/skus/{sku_id}`: SKU lookup and enrichment
- `POST /api/inventory/recommend`: recommend slot for inbound inventory
- `POST /api/inventory/assign`: commit inbound inventory assignment
- `GET /api/inventory/today`: inbound assignments for the current day

### Forecasting

- `GET /api/forecast/summary`: forecast summary table and counts
- `GET /api/forecast/sku/{sku_id}`: detailed history and forecast for one SKU
- `GET /api/forecast/reorder-queue`: actionable reorder candidates
- `POST /api/forecast/reorder/{sku_id}`: create reorder signal

### Static app

- `GET /`: serves the SPA
- `GET /static/*`: frontend assets

## 6. Core Data Dependencies

The application reads from and writes to Oracle warehouse data structures, including:

- `warehouse_zones`
- `slots`
- `inventory`
- `asset_positions`
- `pick_history`
- `daily_sales`
- `product`
- `category`
- `slotting_recommendations`
- `movement_log`
- `slot_assignments`
- `forecast_history`

## 7. Operational Notes

### Default app URL

- `http://<host>:8000/`

### Default app credentials in current config

- username: `admin`
- password: `warehouse123`

### Relevant environment-driven configuration

- `ORACLE_USER`
- `ORACLE_PASSWORD`
- `ORACLE_DSN`
- `ORACLE_CONFIG_DIR`
- `ORACLE_WALLET_DIR`
- `ORACLE_POOL_MIN`
- `ORACLE_POOL_MAX`
- `APP_USERNAME`
- `APP_PASSWORD`
- `SESSION_SECRET`
- `SLOTTING_INTERVAL_SECONDS`
- `ENABLE_SLOTTING_SCHEDULER`
- `CORS_ORIGINS`

## 8. Recommended Use Cases

- Warehouse control tower dashboard for supervisors
- Demo environment for warehouse digitization or Oracle-backed logistics solutions
- Operational cockpit for receiving + slotting + replenishment workflows
- Pilot system for testing fast-pick optimization strategies
- Executive showcase for supply chain visibility and warehouse intelligence

## 9. Bottom Line

WareVision is not just a dashboard. It is an operator-facing warehouse execution support layer that combines:

- visibility
- decision support
- guided actions
- predictive replenishment

Its strongest business story is labor efficiency plus stock availability: place inventory better, move it with less wasted travel, and surface reorder risk before service levels drop.
