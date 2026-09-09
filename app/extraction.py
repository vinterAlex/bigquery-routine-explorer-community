import os
import logging
from google.cloud import bigquery

logger = logging.getLogger(__name__)


def get_client():
    return bigquery.Client()


def _region_for(client, project: str, dataset_id: str, fallback_location: str) -> str:
    """Resolve the correct region-<loc> prefix for INFORMATION_SCHEMA.

    Uses the dataset's own location (the source of truth, since datasets can be
    in any region and a SA does not expose a region). Falls back to the
    configured location if the API call fails or returns nothing usable.
    """
    try:
        ds = client.get_dataset(f"{project}.{dataset_id}")
        loc = getattr(ds, "location", None)
        if loc:
            loc = str(loc).lower()
            return loc if loc.startswith("region-") else f"region-{loc}"
    except Exception as e:
        logger.debug(f"Could not resolve location for {project}.{dataset_id}: {e}")
    if fallback_location:
        fallback_location = fallback_location.lower()
        if fallback_location.startswith("region-"):
            return fallback_location
        return f"region-{fallback_location}"
    return "region-us"


def _run_query(client, project: str, region_prefix: str, ds_id: str, location_hint: str):
    """Run a single INFORMATION_SCHEMA.ROUTINES query in the dataset's region.

    `location_hint` is passed to the query job so BigQuery routes it to the
    right regional cluster (required even though region-prefixed tables are used).
    """
    query = """
        SELECT
            ROUTINE_CATALOG,
            ROUTINE_SCHEMA,
            ROUTINE_NAME,
            ROUTINE_TYPE,
            DATA_TYPE,
            ROUTINE_DEFINITION,
            CREATED,
            SECURITY_TYPE
        FROM `{proj}.{region}.INFORMATION_SCHEMA.ROUTINES`
        WHERE ROUTINE_SCHEMA = @dataset_id
    """.format(proj=project, region=region_prefix)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("dataset_id", "STRING", ds_id)
        ]
    )
    # `project=` pins the query JOB (billing/quota) to the target project being
    # introspected. Without it, the job runs under the client's own default
    # project (inferred from the service-account key) - which silently fails
    # with a permissions error whenever the SA's home project differs from the
    # project(s) listed in BQ_PROJECTS, even if jobUser was granted correctly
    # on the target project as documented in the README.
    return client.query(query, job_config=job_config, location=location_hint, project=project).result()


def _dedupe(routines: list[dict]) -> list[dict]:
    """INFORMATION_SCHEMA can report the same routine multiple times (region
    retry, or eventual-consistency lag right after DDL churn). Keep the first
    occurrence of each FQN, preserving order. Read-only."""
    seen = set()
    out = []
    for r in routines:
        fqn = r.get("fqn")
        if fqn in seen:
            continue
        seen.add(fqn)
        out.append(r)
    return out


def extract_routines(projects: list[str], location: str, dataset_filter: str = None) -> list[dict]:
    client = get_client()
    all_routines = []

    for project in projects:
        try:
            datasets = list(client.list_datasets(project=project))
        except Exception as e:
            logger.error(f"Failed to list datasets for project {project}: {e}")
            continue

        for dataset in datasets:
            ds_id = dataset.dataset_id
            if ds_id.startswith("_"):
                # BigQuery's own convention for hidden/system datasets - most
                # commonly the auto-generated "anonymous" datasets it creates
                # to cache ad-hoc query results. These are never real,
                # user-created datasets and can never contain a routine, so
                # scanning them is pure wasted time (and, in projects with
                # many of them, can turn a refresh into a very long scan).
                continue
            if dataset_filter:
                if dataset_filter not in ds_id:
                    continue

            # Determine the dataset's real region (auto-detect), falling back to config.
            region_prefix = _region_for(client, project, ds_id, location)
            loc_hint = region_prefix.replace("region-", "")

            try:
                results = _run_query(client, project, region_prefix, ds_id, loc_hint)
                got_rows = False
                for row in results:
                    got_rows = True
                    routine = {
                        "project": project,
                        "dataset": ds_id,
                        "name": row.ROUTINE_NAME,
                        "routine_type": row.ROUTINE_TYPE,
                        "data_type": row.DATA_TYPE,
                        "definition": row.ROUTINE_DEFINITION or "",
                        "created": str(row.CREATED) if row.CREATED else None,
                        "last_modified": None,
                        "language": None,
                        "fqn": f"{project}.{ds_id}.{row.ROUTINE_NAME}",
                    }
                    all_routines.append(routine)

                # If the detected region came back empty but the configured one differs
                # and hasn't been tried, retry with the configured region.
                if not got_rows and location and loc_hint.lower() != location.lower():
                    logger.info(
                        f"No routines in {project}.{ds_id} via {region_prefix}; "
                        f"retrying with configured region {location}"
                    )
                    alt_region = _region_for(client, project, ds_id, location)
                    alt_hint = alt_region.replace("region-", "")
                    for row in _run_query(client, project, alt_region, ds_id, alt_hint):
                        all_routines.append({
                            "project": project,
                            "dataset": ds_id,
                            "name": row.ROUTINE_NAME,
                            "routine_type": row.ROUTINE_TYPE,
                            "data_type": row.DATA_TYPE,
                            "definition": row.ROUTINE_DEFINITION or "",
                            "created": str(row.CREATED) if row.CREATED else None,
                            "last_modified": None,
                            "language": None,
                            "fqn": f"{project}.{ds_id}.{row.ROUTINE_NAME}",
                        })
            except Exception as e:
                logger.error(f"Failed to query routines for {project}.{ds_id} in {region_prefix}: {e}")

    return _dedupe(all_routines)
