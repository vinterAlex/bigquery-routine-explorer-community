# BigQuery Routine Explorer

Explore the dependency graph of your BigQuery routines (stored procedures, functions, table-valued functions) in an interactive web app — see who calls what, what reads/writes which tables, and trace data flow forward and backward through your pipeline.

---

## Editions

| Feature | Community | **Full** |
|---|:---:|:---:|
| Interactive dependency graph | ✓ | ✓ |
| Routine detail & SQL viewer | ✓ | ✓ |
| Forward / backward depth tracing | **max 3** | **unlimited** |
| Max routines per load | **50** | **unlimited** |
| BigQuery projects | **1** | **unlimited** |
| Auto-refresh on startup | — | ✓ |
| Dataset name filter | — | ✓ |
| Docker / local run | ✓ | ✓ |
| No data access, read-only by design | ✓ | ✓ |
| Price | **Free** | **One-time purchase** |

> **Upgrade:** [Get the Full Edition on Lemon Squeezy →](https://lemonsqueezy.com/products/bigquery-routine-explorer)

---

## Quick Start (Community Edition)

### 1. Set up secrets

```bash
# Windows (PowerShell):
.\setup_secrets.ps1 -KeyPath "C:\path\to\your-service-account.json"

# Linux / macOS:
chmod +x setup_secrets.sh
./setup_secrets.sh /path/to/your-service-account.json
```

Or just drop your key file into the `secrets/` folder (any filename, no need to rename).

**Required IAM roles** (read-only, never grants data access):
- `roles/bigquery.metadataViewer`
- `roles/bigquery.jobUser`

### 2. Build

```bash
docker build -t routine-explorer-community .
```

### 3. Run

```bash
docker run \
  -v ./secrets:/secrets:ro \
  -e BQ_PROJECTS=my-project \
  -p 8080:8080 \
  routine-explorer-community
```

Or simply **double-click `run_app.bat`** (Windows) — it builds on first run and opens the browser automatically.

Open **http://localhost:8080**, then click **"Refresh from BigQuery"** in the top bar.

---

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `BQ_PROJECTS` | Yes | - | GCP project ID (1 only in Community Edition) |
| `BQ_LOCATION` | No | `us` | Fallback region (auto-detected per dataset normally) |
| `SA_KEY_PATH` | No | `/secrets/key.json` | Path to the mounted service account key |
| `PORT` | No | `8080` | Port to listen on |
| `SEED_DUMMY_DATA` | No | - | `1/true/yes` to load embedded demo routines (testing only, no BigQuery needed) |

### Testing with no BigQuery account

```bash
docker run \
  -v ./secrets:/secrets:ro \
  -e SEED_DUMMY_DATA=1 \
  -p 8080:8080 \
  routine-explorer-community
```

Loads an embedded demo project with 14 routines and 18 tables exercising all dependency types. Click **"Refresh from BigQuery"** to build the graph.

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Web UI |
| `GET /healthz` | Health check |
| `GET /api/edition` | Edition info & limits (Community vs Full) |
| `GET /api/graph?selected=...&forward=2&backward=2` | Full or filtered subgraph |
| `GET /api/routine/{fqn}` | Routine detail (body, detected operations, dynamic-SQL flag) |
| `POST /api/refresh` | Re-extract routines and rebuild the cached graph |
| `GET /api/refresh_status` | Poll refresh progress |

---

## Security

- Credentials are **never** baked into the image — `secrets/` is excluded from the Docker build and mounted read-only at runtime.
- The app only ever issues `SELECT ... FROM INFORMATION_SCHEMA...` queries. It never issues DDL, DML, or `CALL`.
- The service account needs only `roles/bigquery.metadataViewer` + `roles/bigquery.jobUser`.

## Known Limitations

- Dynamic SQL via `EXECUTE IMMEDIATE` cannot be statically parsed — such routines are flagged in the UI rather than silently missing edges.
- Only reads routine metadata/definition text; it never reads table data or executes a routine.