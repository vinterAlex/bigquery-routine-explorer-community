"""Offline dummy routine data used for local testing when the service account is
read-only (or when you simply don't want to write to BigQuery).

The real production path is `extraction.extract_routines`, which queries
INFORMATION_SCHEMA.ROUTINES. This module is only used when SEED_DUMMY_DATA=1,
purely so the UI can be exercised end-to-end with a realistic, interconnected
graph: routines that call other routines, create/insert/delete/merge tables,
read from tables, use dynamic SQL, and spread across two datasets.

Everything here is embedded text - nothing is executed against BigQuery.
"""

PROJECT = "bigquery-healthcheck-dev"


def _fqn(dataset: str, name: str) -> str:
    return f"{PROJECT}.{dataset}.{name}"


# ---------------------------------------------------------------------------
# Dataset 1: landing (raw / source-side data)
# ---------------------------------------------------------------------------

_LANDING = [
    {
        "name": "sp_land_raw_events",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('landing', 'sp_land_raw_events')}`(src STRING)
BEGIN
  CREATE OR REPLACE TABLE `{_fqn('landing', 'raw_events')}`
  AS SELECT event_id, event_type, event_at, payload
     FROM `{_fqn('landing', 'staging_events')}`;

  INSERT INTO `{_fqn('landing', 'ingest_log')}` (source, landed_at)
    VALUES (src, CURRENT_TIMESTAMP());
END
""",
    },
    {
        "name": "fn_xml_to_json",
        "routine_type": "FUNCTION",
        "data_type": "STRING",
        "definition": f"""
CREATE OR REPLACE FUNCTION `{_fqn('landing', 'fn_xml_to_json')}`(raw STRING)
RETURNS STRING
AS (TO_JSON_STRING(STRUCT(raw AS original)));
""",
    },
    {
        "name": "sp_archive_old_events",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('landing', 'sp_archive_old_events')}`(cutoff DATE)
BEGIN
  CREATE OR REPLACE TABLE `{_fqn('landing', 'raw_events_archive')}`
  AS SELECT * FROM `{_fqn('landing', 'raw_events')}` WHERE date < cutoff;

  DELETE FROM `{_fqn('landing', 'raw_events')}` WHERE date < cutoff;

  TRUNCATE TABLE `{_fqn('landing', 'staging_events')}`;

  CALL `{_fqn('landing', 'sp_land_raw_events')}`('reingest');
END
""",
    },
]

# ---------------------------------------------------------------------------
# Dataset 2: demo_warehouse (curated / analytical side)
# ---------------------------------------------------------------------------

_DEMO = [
    {
        "name": "sp_etl_customer_360",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('demo_warehouse', 'sp_etl_customer_360')}`()
BEGIN
  CREATE OR REPLACE TABLE `{_fqn('demo_warehouse', 'customer_360')}`
  AS SELECT c.customer_id, c.name,
            COUNT(o.order_id) AS order_count,
            SUM(o.amount) AS lifetime_value
     FROM `{_fqn('demo_warehouse', 'customers')}` c
     LEFT JOIN `{_fqn('demo_warehouse', 'orders')}` o
       ON c.customer_id = o.customer_id
     GROUP BY c.customer_id, c.name;

  MERGE INTO `{_fqn('demo_warehouse', 'customer_agg')}` AS target
  USING `{_fqn('demo_warehouse', 'customer_360')}` AS source
  ON target.customer_id = source.customer_id
  WHEN MATCHED THEN UPDATE SET order_count = source.order_count
  WHEN NOT MATCHED THEN INSERT (customer_id, order_count)
    VALUES (source.customer_id, source.order_count);
END
""",
    },
    {
        "name": "sp_etl_orders",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('demo_warehouse', 'sp_etl_orders')}`()
BEGIN
  CREATE OR REPLACE TABLE `{_fqn('demo_warehouse', 'orders_aggregate')}`
  AS SELECT o.order_date,
            COUNT(*) AS order_count,
            SUM(o.amount) AS revenue
     FROM `{_fqn('demo_warehouse', 'orders')}` o
     GROUP BY o.order_date;

  INSERT INTO `{_fqn('demo_warehouse', 'order_fact_snapshot')}`
    SELECT * FROM `{_fqn('demo_warehouse', 'orders_aggregate')}`;

  CALL `{_fqn('demo_warehouse', 'sp_etl_daily')}`();
  CALL `{_fqn('demo_warehouse', 'sp_send_alert')}`('orders etl done');
END
""",
    },
    {
        "name": "fn_revenue",
        "routine_type": "FUNCTION",
        "data_type": "FLOAT64",
        "definition": f"""
CREATE OR REPLACE FUNCTION `{_fqn('demo_warehouse', 'fn_revenue')}`(d DATE)
RETURNS FLOAT64
AS (
  (SELECT SUM(revenue) FROM `{_fqn('demo_warehouse', 'orders_aggregate')}`
   WHERE order_date = d)
);
""",
    },
    {
        "name": "sp_recompute_metrics",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('demo_warehouse', 'sp_recompute_metrics')}`()
BEGIN
  CREATE OR REPLACE TABLE `{_fqn('demo_warehouse', 'daily_metrics')}`
  AS SELECT r.order_date,
            IFNULL(`{_fqn('demo_warehouse', 'fn_revenue')}`(r.order_date), 0) AS revenue,
            (SELECT COUNT(*) FROM `{_fqn('demo_warehouse', 'raw_events')}`) AS event_cnt
     FROM `{_fqn('demo_warehouse', 'orders_aggregate')}` r;

  CALL `{_fqn('demo_warehouse', 'sp_etl_customer_360')}`();
  CALL `{_fqn('demo_warehouse', 'sp_send_alert')}`('metrics recomputed');
END
""",
    },
    {
        "name": "sp_full_pipeline",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('demo_warehouse', 'sp_full_pipeline')}`()
BEGIN
  DECLARE run_date DATE DEFAULT CURRENT_DATE();

  CALL `{_fqn('landing', 'sp_land_raw_events')}`('pipeline');
  CALL `{_fqn('landing', 'sp_archive_old_events')}`(run_date);

  CALL `{_fqn('demo_warehouse', 'sp_etl_orders')}`();
  CALL `{_fqn('demo_warehouse', 'sp_recompute_metrics')}`();
  CALL `{_fqn('demo_warehouse', 'sp_build_report')}`();
  CALL `{_fqn('demo_warehouse', 'sp_cleanup')}`(run_date);

  SELECT `{_fqn('demo_warehouse', 'fn_count_events')}`('click') AS total_clicks;

  EXECUTE IMMEDIATE "SELECT CURRENT_TIMESTAMP() AS ts";
END
""",
    },
]

# The six original routines (kept for backwards compatibility / continuity).
_ORIGINAL = [
    {
        "name": "sp_etl_daily",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('demo_warehouse', 'sp_etl_daily')}`()
BEGIN
  CREATE OR REPLACE TABLE `{_fqn('demo_warehouse', 'daily_summary')}` AS
    SELECT date, COUNT(*) AS cnt FROM `{_fqn('demo_warehouse', 'raw_events')}` GROUP BY date;

  INSERT INTO `{_fqn('demo_warehouse', 'daily_summary_agg')}`
    SELECT * FROM `{_fqn('demo_warehouse', 'daily_summary')}`;

  CALL `{_fqn('demo_warehouse', 'sp_send_alert')}`('etl done');
END
""",
    },
    {
        "name": "sp_send_alert",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('demo_warehouse', 'sp_send_alert')}`(IN msg STRING)
BEGIN
  INSERT INTO `{_fqn('demo_warehouse', 'alert_log')}` (message, sent_at)
    VALUES (msg, CURRENT_TIMESTAMP());

  SELECT COUNT(*) AS cnt FROM `{_fqn('demo_warehouse', 'alert_log')}`;
END
""",
    },
    {
        "name": "fn_add",
        "routine_type": "FUNCTION",
        "data_type": "INT64",
        "definition": f"""
CREATE OR REPLACE FUNCTION `{_fqn('demo_warehouse', 'fn_add')}`(a INT64, b INT64)
RETURNS INT64
AS (a + b);
""",
    },
    {
        "name": "sp_build_report",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('demo_warehouse', 'sp_build_report')}`()
BEGIN
  CREATE OR REPLACE TABLE `{_fqn('demo_warehouse', 'report_table')}` AS
    SELECT * FROM `{_fqn('demo_warehouse', 'daily_summary')}`;

  CALL `{_fqn('demo_warehouse', 'sp_send_alert')}`('report ready');

  MERGE INTO `{_fqn('demo_warehouse', 'report_log')}` AS target
  USING `{_fqn('demo_warehouse', 'report_table')}` AS source
  ON target.id = source.id
  WHEN MATCHED THEN UPDATE SET target.updated_at = CURRENT_TIMESTAMP()
  WHEN NOT MATCHED THEN INSERT (id, cnt, updated_at) VALUES (source.id, source.cnt, CURRENT_TIMESTAMP());

  EXECUTE IMMEDIATE "SELECT NULL";
END
""",
    },
    {
        "name": "sp_cleanup",
        "routine_type": "PROCEDURE",
        "data_type": None,
        "definition": f"""
CREATE OR REPLACE PROCEDURE `{_fqn('demo_warehouse', 'sp_cleanup')}`(IN cutoff DATE)
BEGIN
  DELETE FROM `{_fqn('demo_warehouse', 'raw_events')}` WHERE date < cutoff;
  TRUNCATE TABLE `{_fqn('demo_warehouse', 'temp_staging')}`;
END
""",
    },
    {
        "name": "fn_count_events",
        "routine_type": "FUNCTION",
        "data_type": "INT64",
        "definition": f"""
CREATE OR REPLACE FUNCTION `{_fqn('demo_warehouse', 'fn_count_events')}`(metric STRING)
RETURNS INT64
AS (
  (SELECT COUNT(*) FROM `{_fqn('demo_warehouse', 'raw_events')}`
   WHERE metric_name = metric)
);
""",
    },
]

# Optional `created` timestamps so the detail panel has realistic metadata.
_CREATED_BY_NAME = {
    "sp_send_alert": "2024-01-10 08:00:00+00:00",
    "sp_etl_daily": "2024-01-15 08:00:00+00:00",
    "fn_add": "2024-02-01 08:00:00+00:00",
    "sp_build_report": "2024-03-15 08:00:00+00:00",
    "sp_cleanup": "2024-04-01 08:00:00+00:00",
    "fn_count_events": "2024-05-20 08:00:00+00:00",
    "sp_land_raw_events": "2024-06-02 08:00:00+00:00",
    "fn_xml_to_json": "2024-06-10 08:00:00+00:00",
    "sp_archive_old_events": "2024-06-18 08:00:00+00:00",
    "sp_etl_customer_360": "2024-07-01 08:00:00+00:00",
    "sp_etl_orders": "2024-07-05 08:00:00+00:00",
    "fn_revenue": "2024-07-20 08:00:00+00:00",
    "sp_recompute_metrics": "2024-08-01 08:00:00+00:00",
    "sp_full_pipeline": "2024-08-15 08:00:00+00:00",
}


def _materialize(dataset: str, routine: dict) -> dict:
    name = routine["name"]
    return {
        "project": PROJECT,
        "dataset": dataset,
        "name": name,
        "routine_type": routine["routine_type"],
        "data_type": routine.get("data_type"),
        "definition": routine["definition"].strip(),
        "created": _CREATED_BY_NAME.get(name),
        "last_modified": None,
        "language": None,
        "fqn": _fqn(dataset, name),
    }


DUMMY_ROUTINES: list[dict] = (
    [_materialize("landing", r) for r in _LANDING]
    + [_materialize("demo_warehouse", r) for r in _DEMO]
    + [_materialize("demo_warehouse", r) for r in _ORIGINAL]
)

DUMMY_ROUTINE_NAMES = [r["name"] for r in DUMMY_ROUTINES]
