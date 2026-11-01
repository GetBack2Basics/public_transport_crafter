"""Shared helper: tests read lakehouse JSON straight from GCS (no local copies)."""
import json
import os
import urllib.request

GCS_BUCKET = os.environ.get("GCS_BUCKET", "nsw-transit-spatial-crafter")


def load_gcs_lake_json(name: str) -> dict:
    url = f"https://storage.googleapis.com/{GCS_BUCKET}/lake/{name}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

