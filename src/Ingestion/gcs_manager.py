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
DEFAULT_BUCKET = os.environ.get("GCS_BUCKET", "nsw-transit-spatial-crafter")
DATA_DIR = BASE_DIR / "data"


DEFAULT_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or "biblestudy-crafter"


def _get_storage_client():
    """Returns an authenticated google.cloud.storage.Client with resolved project."""
    from google.cloud import storage
    try:
        return storage.Client(project=DEFAULT_PROJECT)
    except Exception:
        return storage.Client()


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

    # Use Python google.cloud.storage SDK directly
    try:
        client = _get_storage_client()
        b = client.bucket(bucket)
        blob = b.blob(gcs_blob_path.lstrip("/"))
        if content_type:
            blob.content_type = content_type
        blob.cache_control = cache_control
        blob.upload_from_filename(str(local_path))
        logger.info(f"Uploaded {local_path.name} to {target_uri} via storage SDK")
        return get_public_gcs_url(gcs_blob_path, bucket)
    except Exception as sdk_err:
        logger.warning(f"Storage SDK upload failed ({sdk_err}), trying gcloud CLI...")

    # Fallback to gcloud storage CLI
    try:
        cmd = ["gcloud", "storage", "cp", str(local_path), target_uri, f"--cache-control={cache_control}"]
        if content_type:
            cmd.append(f"--content-type={content_type}")
        use_shell = sys.platform == "win32"
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, shell=use_shell)
        if res.returncode == 0:
            logger.info(f"Uploaded {local_path.name} to {target_uri} via gcloud")
            return get_public_gcs_url(gcs_blob_path, bucket)
    except Exception as e:
        logger.error(f"Failed to upload {local_path} to GCS: {e}")

    return get_public_gcs_url(gcs_blob_path, bucket)


def upload_directory_to_gcs(
    local_dir: Path,
    gcs_prefix: str,
    bucket_name: Optional[str] = None
) -> None:
    """Recursively uploads a local directory to a GCS prefix via Python SDK."""
    bucket = bucket_name or get_active_gcs_bucket()
    if not local_dir.exists():
        return

    try:
        client = _get_storage_client()
        b = client.bucket(bucket)
        for item in local_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(local_dir).as_posix()
                blob_name = f"{gcs_prefix.strip('/')}/{rel}"
                blob = b.blob(blob_name)
                blob.cache_control = "public, max-age=60"
                if item.suffix == ".html":
                    blob.content_type = "text/html"
                elif item.suffix == ".parquet":
                    blob.content_type = "application/octet-stream"
                blob.upload_from_filename(str(item))
        logger.info(f"Uploaded directory {local_dir} to gs://{bucket}/{gcs_prefix.strip('/')}/")
        return
    except Exception as sdk_err:
        logger.warning(f"Storage SDK directory upload failed ({sdk_err}), trying gcloud storage rsync...")

    try:
        target_uri = f"gs://{bucket}/{gcs_prefix.strip('/')}/"
        cmd = ["gcloud", "storage", "rsync", "-r", str(local_dir), target_uri]
        use_shell = sys.platform == "win32"
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60, shell=use_shell)
        if res.returncode == 0:
            logger.info(f"Synced {local_dir} to {target_uri}")
    except Exception as e:
        logger.warning(f"Directory upload failed: {e}")


def download_blob_from_gcs(
    gcs_blob_path: str,
    local_destination: Path,
    bucket_name: Optional[str] = None
) -> bool:
    """Downloads a blob from GCS to local destination."""
    bucket = bucket_name or get_active_gcs_bucket()
    local_destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        client = _get_storage_client()
        b = client.bucket(bucket)
        blob = b.blob(gcs_blob_path.lstrip("/"))
        if blob.exists():
            blob.download_to_filename(str(local_destination))
            return True
    except Exception as sdk_err:
        logger.warning(f"Storage SDK download failed ({sdk_err}), trying gcloud CLI...")

    try:
        source_uri = f"gs://{bucket}/{gcs_blob_path.lstrip('/')}"
        cmd = ["gcloud", "storage", "cp", source_uri, str(local_destination)]
        use_shell = sys.platform == "win32"
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, shell=use_shell)
        if res.returncode == 0 and local_destination.exists():
            return True
    except Exception:
        pass

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


def list_gcs_files(prefix: str = "", bucket_name: Optional[str] = None) -> List[str]:
    """Lists blob names in the active GCS bucket matching an optional prefix."""
    bucket = bucket_name or get_active_gcs_bucket()
    try:
        client = _get_storage_client()
        b = client.bucket(bucket)
        blobs = b.list_blobs(prefix=prefix)
        return [blob.name for blob in blobs]
    except Exception as e:
        logger.warning(f"Storage SDK list failed ({e}), falling back to gcloud CLI...")

    try:
        target_uri = f"gs://{bucket}/{prefix}*"
        cmd = ["gcloud", "storage", "ls", target_uri]
        use_shell = sys.platform == "win32"
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, shell=use_shell)
        if res.returncode == 0:
            lines = res.stdout.strip().splitlines()
            names = []
            prefix_strip = f"gs://{bucket}/"
            for line in lines:
                clean = line.strip()
                if clean.startswith(prefix_strip):
                    names.append(clean[len(prefix_strip):])
            return names
    except Exception as cmd_err:
        logger.error(f"Failed to list GCS files: {cmd_err}")
    return []

