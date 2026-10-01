from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .field_mapping import DATA_ROOT, TABLE_FILES


@dataclass(slots=True)
class AuditDataBundle:
    package_root: Path
    data_root: Path
    evidence_root: Path
    revenue_rows: list[dict[str, str]]
    bank_rows: list[dict[str, str]]
    contract_rows: list[dict[str, str]]
    invoice_rows: list[dict[str, str]]
    ar_rows: list[dict[str, str]]
    expected_rows: list[dict[str, str]]

    def row_counts(self) -> dict[str, int]:
        return {
            "revenue_detail": len(self.revenue_rows),
            "bank_receipts": len(self.bank_rows),
            "contract_master": len(self.contract_rows),
            "invoice_list": len(self.invoice_rows),
            "ar_detail_or_aging": len(self.ar_rows),
            "expected_findings": len(self.expected_rows),
        }



def _read_csv_rows(file_path: Path) -> list[dict[str, str]]:
    with file_path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))



def load_a101_sample_bundle(package_root: Path | None = None) -> AuditDataBundle:
    from .field_mapping import EVIDENCE_ROOT, PACKAGE_ROOT

    resolved_package_root = package_root or PACKAGE_ROOT
    data_root = resolved_package_root / "01_financial_data"
    evidence_root = resolved_package_root / "02_evidence_files"

    rows = {key: _read_csv_rows(data_root / file_name) for key, file_name in TABLE_FILES.items()}

    return AuditDataBundle(
        package_root=resolved_package_root,
        data_root=data_root,
        evidence_root=evidence_root,
        revenue_rows=rows["revenue"],
        bank_rows=rows["bank"],
        contract_rows=rows["contract"],
        invoice_rows=rows["invoice"],
        ar_rows=rows["ar"],
        expected_rows=rows["expected"],
    )
