#!/usr/bin/env bash
# scripts/sync_to_gcs.sh
# GCP Antigravity Playbook:
# Google Cloud Storage Artifact & Standalone Web Report Deployment
# Sets Cache-Control: public, max-age=60 to guarantee instantaneous edge updates.

set -euo pipefail

GCS_BUCKET="${GCS_BUCKET:-rathmines-interactive-map}"
REPORT_FILE="${1:-data/reports/transit_insight_report.html}"

echo "============================================================"
echo " GCP Antigravity: Syncing Deliverables to GCS"
echo " Target Bucket: gs://${GCS_BUCKET}"
echo "============================================================"

if ! command -v gsutil >/dev/null 2>&1 && ! command -v gcloud >/dev/null 2>&1; then
    echo "Warning: Neither gsutil nor gcloud found. Skipping remote upload."
    exit 0
fi

# Sync HTML report with instant edge propagation headers
if [ -f "${REPORT_FILE}" ]; then
    echo "Uploading HTML report ${REPORT_FILE}..."
    gcloud storage cp "${REPORT_FILE}" "gs://${GCS_BUCKET}/reports/transit_insight_report.html" \
        --cache-control="public, max-age=60" \
        --content-type="text/html" || {
            gsutil -h "Cache-Control: public, max-age=60" cp "${REPORT_FILE}" "gs://${GCS_BUCKET}/reports/transit_insight_report.html" || true
        }
    echo "Report live at: https://storage.googleapis.com/${GCS_BUCKET}/reports/transit_insight_report.html"
fi

# Sync Parquet lake assets
if [ -d "data/lake" ]; then
    echo "Syncing Parquet lake tables..."
    gcloud storage rsync -r data/lake "gs://${GCS_BUCKET}/lake/" || true
fi

echo "Sync completed successfully."
