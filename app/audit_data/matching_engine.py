from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class MatchingResult:
    expected_exception_count: int
    detected_exception_count: int
    matched_exception_count: int
    missed_exception_count: int
    false_positive_count: int
    expected_high_risk_amount: int
    detected_high_risk_amount: int
    amount_difference: int
    evidence_coverage_rate: float
    matched_revenue_ids: list[str]
    missed_revenue_ids: list[str]
    false_positive_revenue_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_exception_count": self.expected_exception_count,
            "detected_exception_count": self.detected_exception_count,
            "matched_exception_count": self.matched_exception_count,
            "missed_exception_count": self.missed_exception_count,
            "false_positive_count": self.false_positive_count,
            "expected_high_risk_amount": self.expected_high_risk_amount,
            "detected_high_risk_amount": self.detected_high_risk_amount,
            "amount_difference": self.amount_difference,
            "evidence_coverage_rate": self.evidence_coverage_rate,
            "matched_revenue_ids": self.matched_revenue_ids,
            "missed_revenue_ids": self.missed_revenue_ids,
            "false_positive_revenue_ids": self.false_positive_revenue_ids,
        }



def match_expected_findings(
    expected_rows: list[dict[str, str]],
    exception_candidates: list[dict[str, Any]],
) -> MatchingResult:
    expected_exceptions = [row for row in expected_rows if row.get("是否异常") == "是"]
    expected_by_revenue = {str(row.get("收入编号") or ""): row for row in expected_exceptions}
    detected_by_revenue = {str(item.get("revenue_id") or ""): item for item in exception_candidates}

    matched_revenue_ids = sorted([revenue_id for revenue_id in detected_by_revenue if revenue_id in expected_by_revenue])
    missed_revenue_ids = sorted([revenue_id for revenue_id in expected_by_revenue if revenue_id not in detected_by_revenue])
    false_positive_revenue_ids = sorted([revenue_id for revenue_id in detected_by_revenue if revenue_id not in expected_by_revenue])

    expected_high_risk_amount = sum(int(float(row.get("金额") or 0)) for row in expected_exceptions if row.get("预期风险等级") == "高")
    detected_high_risk_amount = sum(
        int(float(item.get("amount") or 0)) for item in exception_candidates if str(item.get("risk_level") or "").lower() == "high"
    )

    total_expected_evidence = 0
    matched_expected_evidence = 0
    for row in expected_exceptions:
        tokens = [token.strip() for token in str(row.get("对应证据文件") or "").split(";") if token.strip()]
        total_expected_evidence += len(tokens)
        candidate = detected_by_revenue.get(str(row.get("收入编号") or ""))
        candidate_files = {str(ref.get("file_name") or "") for ref in list(candidate.get("evidence_refs") or [])} if candidate else set()
        matched_expected_evidence += sum(1 for token in tokens if token in candidate_files)

    coverage_rate = round((matched_expected_evidence / total_expected_evidence), 4) if total_expected_evidence else 0.0

    return MatchingResult(
        expected_exception_count=len(expected_exceptions),
        detected_exception_count=len(exception_candidates),
        matched_exception_count=len(matched_revenue_ids),
        missed_exception_count=len(missed_revenue_ids),
        false_positive_count=len(false_positive_revenue_ids),
        expected_high_risk_amount=expected_high_risk_amount,
        detected_high_risk_amount=detected_high_risk_amount,
        amount_difference=detected_high_risk_amount - expected_high_risk_amount,
        evidence_coverage_rate=coverage_rate,
        matched_revenue_ids=matched_revenue_ids,
        missed_revenue_ids=missed_revenue_ids,
        false_positive_revenue_ids=false_positive_revenue_ids,
    )
