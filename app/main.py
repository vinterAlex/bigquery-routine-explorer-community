import os
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from .extraction import extract_routines
from .graph import build_graph, save_graph, load_graph, get_subgraph
from .models import GraphSnapshot
from .seed import DUMMY_ROUTINES
from . import license as lic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"BigQuery Routine Explorer — {lic.EDITION.upper()} EDITION")


def _looks_like_service_account_key(path: str) -> bool:
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return False
    return isinstance(data, dict) and data.get("type") == "service_account" and "private_key" in data


def _find_service_account_key(preferred_path: str) -> str | None:
    if os.path.isfile(preferred_path):
        return preferred_path
    secrets_dir = os.path.dirname(preferred_path) or "."
    if not os.path.isdir(secrets_dir):
        return None
    candidates = [
        os.path.join(secrets_dir, fname)
        for fname in sorted(os.listdir(secrets_dir))
        if fname.lower().endswith(".json") and _looks_like_service_account_key(os.path.join(secrets_dir, fname))
    ]
    if not candidates:
        return None
    if len(candidates) > 1:
        logger.warning(f"Multiple SA keys found in {secrets_dir}; using {candidates[0]}.")
    return candidates[0]


def setup_credentials():
    sa_key_path = os.environ.get("SA_KEY_PATH", "/secrets/key.json")
    resolved = _find_service_account_key(sa_key_path)
    if resolved:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = resolved
        logger.info(f"Using SA key at {resolved}")
    else:
        logger.warning(f"No SA key found at {sa_key_path}; ADC will be used.")


def is_seed_enabled() -> bool:
    return os.environ.get("SEED_DUMMY_DATA", "").strip().lower() in ("1", "true", "yes")


def _enforce_community_limits(routines: list[dict]) -> tuple[list[dict], bool]:
    """Apply Community Edition routine-count limit. Returns (list, was_truncated)."""
    truncated = False
    if len(routines) > lic.MAX_ROUTINES:
        logger.warning(
            f"Community Edition: only first {lic.MAX_ROUTINES} of {len(routines)} routines loaded. "
            f"Upgrade to the Full Edition for unlimited routines."
        )
        routines = routines[: lic.MAX_ROUTINES]
        truncated = True
    return routines, truncated


def do_refresh() -> dict:
    setup_credentials()
    raw_projects = [p.strip() for p in os.environ.get("BQ_PROJECTS", "").split(",") if p.strip()]
    location = os.environ.get("BQ_LOCATION", "us")
    dataset_filter = os.environ.get("DATASET_FILTER") or None if lic.ALLOW_DATASET_FILTER else None

    seed_mode = is_seed_enabled()
    if seed_mode:
        logger.info("SEED_DUMMY_DATA set — using embedded demo routines.")
        routines = list(DUMMY_ROUTINES)
    else:
        if not raw_projects:
            return {"error": "BQ_PROJECTS env var not set."}
        if len(raw_projects) > lic.MAX_PROJECTS:
            logger.warning(
                f"Community Edition: {lic.MAX_PROJECTS} project(s) only. Got {len(raw_projects)}: {raw_projects}. "
                f"Using first: {raw_projects[0]}. Upgrade to Full Edition for multi-project support."
            )
            raw_projects = raw_projects[: lic.MAX_PROJECTS]
        routines = extract_routines(raw_projects, location, dataset_filter)

    routines, truncated = _enforce_community_limits(routines)
    snap = build_graph(routines)
    save_graph(snap)
    return {
        "status": "ok",
        "routine_count": len(routines),
        "node_count": len(snap.nodes),
        "edge_count": len(snap.edges),
        "source": "dummy" if seed_mode else "bigquery",
        "community_limited": truncated,
    }


_refresh_lock = threading.Lock()
_refresh_state = {"status": "idle", "started_at": None, "result": None, "error": None}


def _run_refresh_in_background() -> bool:
    with _refresh_lock:
        if _refresh_state["status"] == "running":
            return False
        _refresh_state["status"] = "running"
        _refresh_state["started_at"] = time.time()
        _refresh_state["result"] = None
        _refresh_state["error"] = None

    def _worker():
        try:
            result = do_refresh()
            with _refresh_lock:
                if "error" in result:
                    _refresh_state["status"] = "error"
                    _refresh_state["error"] = result["error"]
                else:
                    _refresh_state["status"] = "done"
                    _refresh_state["result"] = result
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            with _refresh_lock:
                _refresh_state["status"] = "error"
                _refresh_state["error"] = str(e)

    threading.Thread(target=_worker, daemon=True).start()
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_credentials()
    refresh_on_start = os.environ.get("REFRESH_ON_START", "").strip().lower() in ("1", "true", "yes")
    if refresh_on_start and lic.ALLOW_REFRESH_ON_START:
        logger.info("REFRESH_ON_START enabled — starting background scan.")
        _run_refresh_in_background()
    elif refresh_on_start and not lic.ALLOW_REFRESH_ON_START:
        logger.warning(
            "REFRESH_ON_START is set but disabled in the Community Edition. "
            "Click 'Refresh from BigQuery' in the UI instead."
        )
    yield


app = FastAPI(title="BigQuery Routine Explorer (Community)", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "edition": lic.EDITION}


@app.get("/api/edition")
def api_edition():
    return {
        "edition": lic.EDITION,
        "badge": lic.EDITION_BADGE,
        "purchase_url": lic.PURCHASE_URL,
        "limits": {
            "max_projects": lic.MAX_PROJECTS,
            "max_routines": lic.MAX_ROUTINES,
            "max_forward_depth": lic.MAX_FORWARD_DEPTH,
            "max_backward_depth": lic.MAX_BACKWARD_DEPTH,
            "refresh_on_start": lic.ALLOW_REFRESH_ON_START,
            "dataset_filter": lic.ALLOW_DATASET_FILTER,
        },
    }


@app.get("/api/graph")
def api_graph(selected: str = Query(None), forward: int = Query(2), backward: int = Query(2)):
    snap = load_graph()
    if not snap:
        return JSONResponse({"error": "No graph built yet. Call POST /api/refresh first."}, status_code=404)
    forward = min(forward, lic.MAX_FORWARD_DEPTH)
    backward = min(backward, lic.MAX_BACKWARD_DEPTH)
    if selected:
        snap = get_subgraph(snap, selected, forward, backward)
    return {
        "nodes": [n.model_dump() for n in snap.nodes],
        "edges": [e.model_dump(by_alias=True) for e in snap.edges],
        "routines_metadata": snap.routines_metadata,
        "edition": lic.EDITION,
    }


@app.get("/api/routine/{fqn:path}")
def api_routine(fqn: str):
    snap = load_graph()
    if not snap:
        return JSONResponse({"error": "No graph built yet."}, status_code=404)
    meta = snap.routines_metadata.get(fqn)
    if not meta:
        return JSONResponse({"error": f"Routine {fqn} not found."}, status_code=404)
    parts = fqn.split(".")
    return {
        "fqn": fqn,
        "name": parts[-1],
        "dataset": parts[-2] if len(parts) >= 2 else "",
        "project": parts[0] if len(parts) >= 3 else "",
        "routine_type": meta.get("routine_type"),
        "language": meta.get("language"),
        "definition": meta.get("definition"),
        "created": meta.get("created"),
        "last_modified": meta.get("last_modified"),
        "has_dynamic_sql": meta.get("has_dynamic_sql", False),
        "operation_types": meta.get("operation_types", []),
        "detected_operations": meta.get("detected_operations", []),
    }


@app.post("/api/refresh")
def api_refresh():
    started = _run_refresh_in_background()
    if not started:
        return {"status": "already_running"}
    return {"status": "started"}


@app.get("/api/refresh_status")
def api_refresh_status():
    with _refresh_lock:
        state = dict(_refresh_state)
    if state["status"] == "running" and state["started_at"]:
        state["elapsed_seconds"] = round(time.time() - state["started_at"], 1)
    return state


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))