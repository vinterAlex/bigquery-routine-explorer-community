"""Community Edition license & feature limits.

These constants control what the Community Edition allows.
The Full Edition (licensed via Lemon Squeezy) removes all of these limits.
"""
import os

# ---- Edition metadata ------------------------------------------------------
EDITION = "community"
EDITION_BADGE = "COMMUNITY"
PURCHASE_URL = os.environ.get(
    "BQRE_FULL_EDITION_URL",
    "https://lemonsqueezy.com/products/bigquery-routine-explorer"
)

# ---- Feature limits --------------------------------------------------------
# Community Edition is limited to a single BigQuery project.
MAX_PROJECTS = 1

# Soft cap on the number of routines loaded in a single refresh.
# Beyond this, the list is truncated and a warning is shown in the UI.
MAX_ROUTINES = 50

# Maximum forward / backward graph traversal depth in the UI.
MAX_FORWARD_DEPTH = 3
MAX_BACKWARD_DEPTH = 3

# REFRESH_ON_START is disabled in the Community Edition (manual refresh only).
ALLOW_REFRESH_ON_START = False

# DATASET_FILTER is disabled in the Community Edition.
ALLOW_DATASET_FILTER = False
