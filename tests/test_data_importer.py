"""
tests/test_data_importer.py
Tests 3-Tier Anti-Mock defense model and ingestion engine contracts.
"""

import os
import io
import pytest
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

from src.Ingestion.data_importer import (
    assert_tier1_pre_execution_contract,
    assert_tier2_physical_artifact_magic_bytes,
    assert_tier3_deep_response_inspection,
    export_tables_to_parquet
)


def test_tier1_contract_rejects_untrusted_domain():
    """Tier 1 must reject endpoints not hosted on authoritative TfNSW domain."""
    bad_config = {
        "source_id": "malicious_feed",
        "protocol": "tfnsw_api",
        "endpoint": "https://untrusted-api.fake-domain.com/gtfs.zip",
        "headers": {},
        "format": "gtfs_zip",
        "target_tables": ["routes"],
        "destination": "data/lake/test.parquet"
    }
    with pytest.raises(AssertionError, match="TIER 1 VIOLATION: Illegal untrusted endpoint"):
        assert_tier1_pre_execution_contract(bad_config)


def test_tier1_contract_asserts_missing_api_key(monkeypatch):
    """Tier 1 must reject missing or placeholder TfNSW API token."""
    monkeypatch.delenv("TFNSW_API_KEY", raising=False)
    config = {
        "source_id": "test_feed",
        "protocol": "tfnsw_api",
        "endpoint": "https://api.transport.nsw.gov.au/v1/gtfs/schedule/buses/hunter",
        "headers": {"Authorization": "apikey ${TFNSW_API_KEY}"},
        "format": "gtfs_zip",
        "target_tables": ["routes"],
        "destination": "data/lake/test.parquet"
    }
    with pytest.raises(AssertionError, match="TIER 1 VIOLATION: Missing or invalid TfNSW API token"):
        assert_tier1_pre_execution_contract(config)


def test_tier2_magic_bytes_check_on_valid_parquet(tmp_path):
    """Tier 2 must pass for valid non-empty Parquet files with b'PAR1' header."""
    test_parquet = tmp_path / "valid.parquet"
    df = pd.DataFrame({"col_a": [1, 2, 3], "col_b": ["x", "y", "z"]})
    df.to_parquet(test_parquet, engine="pyarrow")

    # Should execute without error
    assert_tier2_physical_artifact_magic_bytes(test_parquet, min_bytes=100)

    # Corrupt the header magic bytes
    with open(test_parquet, "r+b") as f:
        f.seek(0)
        f.write(b"FAKE")

    with pytest.raises(AssertionError, match="File failed Parquet magic bytes header check"):
        assert_tier2_physical_artifact_magic_bytes(test_parquet, min_bytes=100)


def test_tier3_deep_response_rejects_html_error_page():
    """Tier 3 must reject HTML landing pages disguised with 200 OK."""
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        text = "<html><body>Login Required / Error 404</body></html>"
        content = b"<html><body>Login Required / Error 404</body></html>"

    with pytest.raises(AssertionError, match="TIER 3 VIOLATION: Received invalid Content-Type"):
        assert_tier3_deep_response_inspection(FakeResponse())


def test_tier3_deep_response_detects_json_fault_in_200_ok():
    """Tier 3 must catch upstream faults masked inside HTTP 200 OK JSON payloads."""
    class FakeFaultResponse:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        def json(self):
            return {"error": {"code": 401, "message": "Invalid API token"}}

    with pytest.raises(AssertionError, match="Upstream API reported error inside 200 OK body"):
        assert_tier3_deep_response_inspection(FakeFaultResponse())
