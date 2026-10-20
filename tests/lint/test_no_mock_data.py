"""
tests/lint/test_no_mock_data.py
Automated AST & Regex Scanner: Breaks CI/CD build on synthetic mock patterns.
Enforces the GetBack2Basics AI Anti-Mock & Hallucination Defense Model.
"""
import os
import re
import glob
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AUDIT_PATTERNS = [
    os.path.join(BASE_DIR, "src", "**", "*.py"),
    os.path.join(BASE_DIR, "runner", "**", "*.py"),
    os.path.join(BASE_DIR, "scripts", "**", "*.sh"),
]

FORBIDDEN_PATTERNS = [
    (r"sampleFeatures\s*=\s*\[", "Hardcoded sample features array (sampleFeatures = [...])"),
    (r"mock_data\s*=\s*", "Explicit mock data variable (mock_data = ...)"),
    (r"dummy_records\s*=\s*", "Dummy records variable (dummy_records = ...)"),
    (r"dummy_trips\s*=\s*", "Dummy trips variable (dummy_trips = ...)"),
    (r"placeholder_count\s*=\s*", "Placeholder record count (placeholder_count = ...)"),
    (r"fake_coordinates\s*=\s*", "Fake coordinates variable (fake_coordinates = ...)"),
    (r"unittest\.mock", "unittest.mock usage prohibited in production code"),
]

def get_files_to_audit():
    files = []
    for pattern in AUDIT_PATTERNS:
        files.extend(glob.glob(pattern, recursive=True))
    return sorted(list(set(files)))

def test_no_mock_or_placeholder_data_in_source():
    files = get_files_to_audit()
    assert len(files) > 0, "No source files found for zero-mock audit"
    for filepath in files:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        rel_path = os.path.relpath(filepath, BASE_DIR)
        for pattern, description in FORBIDDEN_PATTERNS:
            match = re.search(pattern, content)
            assert not match, (
                f"Zero-Mock Violation in {rel_path}!\n"
                f"Found forbidden pattern: {description}\n"
                f"Matched snippet: '{match.group(0) if match else ''}'"
            )
