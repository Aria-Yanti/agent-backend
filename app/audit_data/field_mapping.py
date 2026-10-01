from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "sample_data" / "a101_revenue_test"
DATA_ROOT = PACKAGE_ROOT / "01_financial_data"
EVIDENCE_ROOT = PACKAGE_ROOT / "02_evidence_files"

TABLE_FILES = {
    "revenue": "revenue_detail.csv",
    "bank": "bank_receipts.csv",
    "contract": "contract_master.csv",
    "invoice": "invoice_list.csv",
    "ar": "ar_detail_or_aging.csv",
    "expected": "expected_findings.csv",
}

EVIDENCE_TYPE_BY_PREFIX = {
    "HT": "contract",
    "FP": "invoice",
    "BS": "bank_slip",
    "ACC": "acceptance",
    "AUTH": "authorization",
}
