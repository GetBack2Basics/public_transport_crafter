#!/usr/bin/env python3
"""
src/Ingestion/lake_io.py
GCS-only I/O helpers for pipeline scripts.

The local workspace holds code and docs only: lake data is read straight from
gs://<bucket>/lake/ and published back through short-lived temp files that are
deleted immediately. Nothing here ever keeps a persistent local copy.
"""

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, List, Optional

from src.Ingestion.gcs_manager import (
    download_blob_from_gcs,
    get_active_gcs_bucket,
    list_gcs_files,
    upload_file_to_gcs,
)

logger = logging.getLogger("lake_io")


def get_lake_engine():
    """GcsQueryEngine connected to GCS (raises if the cloud store is unreachable)."""
    from src.Query.gcs_query_engine import GcsQueryEngine
    engine = GcsQueryEngine(bucket_name=get_active_gcs_bucket())
    if engine.fs is None:
        raise RuntimeError("Lakehouse engine is not on GCS; refusing to run pipeline on local files.")
    return engine


def read_lake_json(name: str, default: Optional[Any] = None) -> Any:
    """Reads lake/<name> (JSON) from GCS. Returns `default` if the object is missing."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / name
        if download_blob_from_gcs(f"lake/{name}", dest, bucket_name=get_active_gcs_bucket()):
            return json.loads(dest.read_text(encoding="utf-8"))
    return default


def publish_lake_json(name: str, obj: Any, cache_control: str = "public, max-age=300", indent: Optional[int] = None) -> None:
    """Writes obj to a temp file and uploads it to lake/<name> on GCS."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / name
        seps = None if indent else (",", ":")
        out.write_text(json.dumps(obj, indent=indent, separators=seps, default=str), encoding="utf-8")
        upload_file_to_gcs(out, f"lake/{name}", content_type="application/json; charset=utf-8", cache_control=cache_control)
    logger.info(f"Published gs://{get_active_gcs_bucket()}/lake/{name}")


def publish_text(blob_path: str, text: str, content_type: str, cache_control: str = "public, max-age=300") -> None:
    """Uploads generated text content (HTML etc.) to an arbitrary blob path via a temp file."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / Path(blob_path).name
        out.write_text(text, encoding="utf-8")
        upload_file_to_gcs(out, blob_path, content_type=content_type, cache_control=cache_control)


def list_lake_parquet() -> dict:
    """{filename: size_bytes} for the Parquet objects currently in lake/ on GCS."""
    from src.Ingestion.gcs_manager import _get_storage_client
    client = _get_storage_client()
    return {
        b.name.split("/", 1)[1]: b.size
        for b in client.list_blobs(get_active_gcs_bucket(), prefix="lake/")
        if b.name.endswith(".parquet")
    }
