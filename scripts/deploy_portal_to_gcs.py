#!/usr/bin/env python3
"""
scripts/deploy_portal_to_gcs.py
Deploys the NSW Public Transport Planning Portal to Google Cloud Storage.
Ensures the web interface, styles, and logic are hosted on GCS:
https://storage.googleapis.com/nsw-transit-spatial-crafter/index.html
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.Ingestion.gcs_manager import upload_file_to_gcs, get_active_gcs_bucket

STATIC_DIR = BASE_DIR / "src" / "Web" / "static"


def deploy_portal():
    bucket = get_active_gcs_bucket()
    print(f"Deploying NSW Transit Planning Portal to gs://{bucket}...")

    # Upload index.html at root of bucket and /index.html
    index_file = STATIC_DIR / "index.html"
    url1 = upload_file_to_gcs(index_file, "index.html", content_type="text/html; charset=utf-8", cache_control="public, max-age=60")
    upload_file_to_gcs(index_file, "planning_portal.html", content_type="text/html; charset=utf-8", cache_control="public, max-age=60")

    # Upload static/style.css
    css_file = STATIC_DIR / "style.css"
    upload_file_to_gcs(css_file, "static/style.css", content_type="text/css; charset=utf-8", cache_control="public, max-age=60")
    upload_file_to_gcs(css_file, "style.css", content_type="text/css; charset=utf-8", cache_control="public, max-age=60")

    # Upload static/app.js
    js_file = STATIC_DIR / "app.js"
    upload_file_to_gcs(js_file, "static/app.js", content_type="application/javascript; charset=utf-8", cache_control="public, max-age=60")
    upload_file_to_gcs(js_file, "app.js", content_type="application/javascript; charset=utf-8", cache_control="public, max-age=60")

    # Upload data_qa.html
    qa_file = STATIC_DIR / "data_qa.html"
    upload_file_to_gcs(qa_file, "data_qa.html", content_type="text/html; charset=utf-8", cache_control="no-cache, max-age=0")
    upload_file_to_gcs(qa_file, "qa.html", content_type="text/html; charset=utf-8", cache_control="no-cache, max-age=0")

    # Upload data_qa.js
    qa_js_file = STATIC_DIR / "data_qa.js"
    upload_file_to_gcs(qa_js_file, "data_qa.js", content_type="application/javascript; charset=utf-8", cache_control="no-cache, max-age=0")
    upload_file_to_gcs(qa_js_file, "static/data_qa.js", content_type="application/javascript; charset=utf-8", cache_control="no-cache, max-age=0")

    # Upload GeoLibre Map Inspector (standalone and docs/qa)
    inspect_file = STATIC_DIR / "geolibre_qa_inspect.html"
    if inspect_file.exists():
        upload_file_to_gcs(inspect_file, "geolibre_qa_inspect.html", content_type="text/html; charset=utf-8", cache_control="no-cache, max-age=0")

    inspect_docs_file = STATIC_DIR / "docs" / "qa" / "geolibre_qa_inspect.html"
    if inspect_docs_file.exists():
        upload_file_to_gcs(inspect_docs_file, "docs/qa/geolibre_qa_inspect.html", content_type="text/html; charset=utf-8", cache_control="no-cache, max-age=0")
    elif inspect_file.exists():
        upload_file_to_gcs(inspect_file, "docs/qa/geolibre_qa_inspect.html", content_type="text/html; charset=utf-8", cache_control="no-cache, max-age=0")

    # Upload Data QA Manifest & Routes Catalog
    manifest_file = BASE_DIR / "data" / "lake" / "nsw_data_qa_manifest.json"
    if manifest_file.exists():
        upload_file_to_gcs(manifest_file, "lake/nsw_data_qa_manifest.json", content_type="application/json", cache_control="public, max-age=120")

    catalog_file = BASE_DIR / "data" / "lake" / "nsw_routes_catalog.json"
    if catalog_file.exists():
        upload_file_to_gcs(catalog_file, "lake/nsw_routes_catalog.json", content_type="application/json", cache_control="public, max-age=300")

    index_file = BASE_DIR / "data" / "lake" / "nsw_route_lookup_index.json"
    if index_file.exists():
        upload_file_to_gcs(index_file, "lake/nsw_route_lookup_index.json", content_type="application/json", cache_control="public, max-age=300")

    opts_file = BASE_DIR / "data" / "lake" / "nsw_timetable_optimizations.json"
    if opts_file.exists():
        upload_file_to_gcs(opts_file, "lake/nsw_timetable_optimizations.json", content_type="application/json", cache_control="no-cache, max-age=0")

    active_geoms_file = BASE_DIR / "data" / "lake" / "nsw_active_route_geometries.json"
    if active_geoms_file.exists():
        upload_file_to_gcs(active_geoms_file, "lake/nsw_active_route_geometries.json", content_type="application/json", cache_control="public, max-age=300")

    interchanges_file = BASE_DIR / "data" / "lake" / "nsw_interchanges.json"
    if interchanges_file.exists():
        upload_file_to_gcs(interchanges_file, "lake/nsw_interchanges.json", content_type="application/json", cache_control="public, max-age=300")

    print(f"\nSuccessfully deployed to GCS!")
    print(f"Planning Portal URL: https://storage.googleapis.com/{bucket}/index.html")
    print(f"Data QA Hub URL:     https://storage.googleapis.com/{bucket}/data_qa.html")
    print(f"GeoLibre Inspect:    https://storage.googleapis.com/{bucket}/geolibre_qa_inspect.html")
    return url1


if __name__ == "__main__":
    deploy_portal()
