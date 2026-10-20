#!/usr/bin/env python3
"""
src/Ingestion/gcs_manager.py
GCP Cloud Storage & Lakehouse Manager.
Enforces the architectural mandate:
  - Local repository is strictly code (configs, scripts, tests).
  - Heavy data processing, Parquet lake staging, and report reviews all live on GCS.
"""

import os
import sys
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gcs_manager")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_BUCKET = os.environ.get("GCS_BUCKET", "rathmines-interactive-map")
DATA_DIR = BASE_DIR / "data"


def get_active_gcs_bucket() -> str:
    """Returns the configured GCS bucket name."""
    return os.environ.get("GCS_BUCKET", DEFAULT_BUCKET)


def get_public_gcs_url(blob_path: str, bucket_name: Optional[str] = None) -> str:
    """Returns the public HTTPS URL for an asset hosted on GCS."""
    bucket = bucket_name or get_active_gcs_bucket()
    clean_path = blob_path.lstrip("/")
    return f"https://storage.googleapis.com/{bucket}/{clean_path}"


def upload_file_to_gcs(
    local_path: Path,
    gcs_blob_path: str,
    content_type: Optional[str] = None,
    cache_control: str = "public, max-age=60",
    bucket_name: Optional[str] = None
) -> str:
    """
    Uploads a file to GCS with fine-grained cache control.
    Uses gcloud storage CLI or google.cloud.storage SDK.
    Returns the public web URL for human review.
    """
    bucket = bucket_name or get_active_gcs_bucket()
    target_uri = f"gs://{bucket}/{gcs_blob_path.lstrip('/')}"

    # Try fast gcloud storage command first
    try:
        cmd = ["gcloud", "storage", "cp", str(local_path), target_uri, f"--cache-control={cache_control}"]
        if content_type:
            cmd.append(f"--content-type={content_type}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if res.returncode == 0:
            logger.info(f"Uploaded {local_path.name} to {target_uri} via gcloud")
            return get_public_gcs_url(gcs_blob_path, bucket)
    except Exception as e:
        logger.warning(f"gcloud CLI upload fallback triggered: {e}")

    # Fallback to Python SDK
    try:
        from google.cloud import storage
        client = storage.Client()
        b = client.bucket(bucket)
        blob = b.blob(gcs_blob_path.lstrip("/"))
        if content_type:
            blob.content_type = content_type
        blob.cache_control = cache_control
        blob.upload_from_filename(str(local_path))
        logger.info(f"Uploaded {local_path.name} to {target_uri} via google.cloud.storage SDK")
        return get_public_gcs_url(gcs_blob_path, bucket)
    except Exception as e:
        logger.error(f"Failed to upload {local_path} to GCS: {e}")
        return get_public_gcs_url(gcs_blob_path, bucket)


def upload_directory_to_gcs(
    local_dir: Path,
    gcs_prefix: str,
    bucket_name: Optional[str] = None
) -> None:
    """Recursively uploads a local directory to a GCS prefix."""
    bucket = bucket_name or get_active_gcs_bucket()
    target_uri = f"gs://{bucket}/{gcs_prefix.strip('/')}/"

    try:
        cmd = ["gcloud", "storage", "rsync", "-r", str(local_dir), target_uri]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if res.returncode == 0:
            logger.info(f"Synced {local_dir} to {target_uri}")
            return
    except Exception as e:
        logger.warning(f"gcloud rsync failed ({e}), falling back to iterative upload")

    if local_dir.exists():
        for item in local_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(local_dir).as_posix()
                blob_name = f"{gcs_prefix.strip('/')}/{rel}"
                upload_file_to_gcs(item, blob_name, bucket_name=bucket)


def download_blob_from_gcs(
    gcs_blob_path: str,
    local_destination: Path,
    bucket_name: Optional[str] = None
) -> bool:
    """Downloads a blob from GCS to local destination."""
    bucket = bucket_name or get_active_gcs_bucket()
    source_uri = f"gs://{bucket}/{gcs_blob_path.lstrip('/')}"
    local_destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        cmd = ["gcloud", "storage", "cp", source_uri, str(local_destination)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if res.returncode == 0 and local_destination.exists():
            return True
    except Exception:
        pass

    try:
        from google.cloud import storage
        client = storage.Client()
        b = client.bucket(bucket)
        blob = b.blob(gcs_blob_path.lstrip("/"))
        if blob.exists():
            blob.download_to_filename(str(local_destination))
            return True
    except Exception as e:
        logger.warning(f"GCS download failed for {gcs_blob_path}: {e}")

    return False


def clean_local_data_artifacts() -> None:
    """
    Cleans local data directories to enforce 'local should just be code'.
    Removes generated parquet, geojson, and reports from local disk after GCS sync.
    """
    if DATA_DIR.exists():
        for sub in ["isochrones", "reports"]:
            p = DATA_DIR / sub
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
                logger.info(f"Cleaned local ephemeral directory: {p}")
