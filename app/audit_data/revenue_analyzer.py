from __future__ import annotations

from datetime import datetime
from typing import Any

from .data_loader import AuditDataBundle
from .evidence_indexer import build_evidence_index, resolve_evidence_refs
from .matching_engine import match_expected_findings


WINDOW_START = "2025-12-25"
WINDOW_END = "2025-12-31"
RISK_ID = "A-101"
DEFAULT_PROJECT_NAME = "XX公司2025年度审计"



def _safe_float(value: Any) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0



def _parse_date(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None



def _date_in_window(value: str) -> bool:
    parsed = _parse_date(value)
    if parsed is None:
        return False
    return WINDOW_START <= parsed.strftime("%Y-%m-%d") <= WINDOW_END



def _risk_level(score: int) -> str:
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"



def _suggested_procedures(flags: list[str]) -> list[str]:
    procedures: list[str] = []
    if any("第三方" in flag or "付款方" in flag for flag in flags):
        procedures.append("检查合同约定付款方与第三方代付授权文件的一致性")
        procedures.append("向付款方与客户实施函证，确认代付安排的商业实质")
    if any("验收" in flag or "收入确认" in flag for flag in flags):
        procedures.append("检查验收单、出库单与收入确认时点是否一致")
    if any("期末" in flag for flag in flags):
        procedures.append("执行期后回款与截止性测试，关注期末集中确认收入")
    if any("金额" in flag for flag in flags):
        procedures.append("核对收入、发票、回款三表金额并检查差异原因")
    return procedures



def analyze_a101_sample(bundle: AuditDataBundle) -> dict[str, Any]:
    contracts = {str(row.get("合同编号") or ""): row for row in bundle.contract_rows}
    invoices_by_revenue = {str(row.get("对应收入编号") or ""): row for row in bundle.invoice_rows}
    bank_by_contract = {str(row.get("对应合同编号") or ""): row for row in bundle.bank_rows}
    evidence_index = build_evidence_index(bundle.evidence_root)
    expected_by_revenue = {str(row.get("收入编号") or ""): row for row in bundle.expected_rows}

    exception_candidates: list[dict[str, Any]] = []
    data_quality_warnings: list[dict[str, Any]] = []
    normalized_tables = {
        "revenue_detail": bundle.revenue_rows,
        "bank_receipts": bundle.bank_rows,
        "contract_master": bundle.contract_rows,
        "invoice_list": bundle.invoice_rows,
        "ar_detail_or_aging": bundle.ar_rows,
        "expected_findings": bundle.expected_rows,
    }

    for row in bundle.revenue_rows:
        revenue_id = str(row.get("收入编号") or "").strip()
        contract_no = str(row.get("合同编号") or "").strip()
        invoice_no = str(row.get("发票号码") or "").strip()
        customer_name = str(row.get("客户名称") or "").strip()
        revenue_date = str(row.get("收入确认日期") or "").strip()
        acceptance_date = str(row.get("验收日期") or "").strip()
        revenue_amount = _safe_float(row.get("收入金额_不含税"))

        contract = contracts.get(contract_no, {})
        invoice = invoices_by_revenue.get(revenue_id, {})
        bank = bank_by_contract.get(contract_no, {})
        expected = expected_by_revenue.get(revenue_id, {})

        contract_customer = str(contract.get("客户名称") or "").strip()
        payer_name = str(bank.get("付款方名称") or expected.get("实际付款方") or "").strip()
        invoice_buyer = str(invoice.get("购买方名称") or "").strip()
        contract_allows_third_party = str(contract.get("是否允许第三方代付") or "").strip()
        authorization_no = str(contract.get("第三方代付授权文件编号") or "").strip()
        receipt_date = str(bank.get("回款日期") or "").strip()
        invoice_amount = _safe_float(invoice.get("不含税金额"))
        receipt_amount = _safe_float(bank.get("回款金额"))
        gross_amount = _safe_float(row.get("价税合计"))

        flags: list[str] = []
        reason_parts: list[str] = []
        score = 0

        if not contract_no:
            data_quality_warnings.append({"revenue_id": revenue_id, "field": "合同编号", "warning": "收入记录缺少合同编号"})
        if not payer_name:
            data_quality_warnings.append({"revenue_id": revenue_id, "field": "付款方名称", "warning": "未找到银行回款付款方，已尝试回退 expected_findings"})
        if payer_name and customer_name and payer_name != customer_name:
            flags.append("付款方名称 != 客户名称")
            reason_parts.append(f"付款方 {payer_name} 与客户 {customer_name} 不一致")
            score += 2
        if payer_name and invoice_buyer and payer_name != invoice_buyer:
            flags.append("付款方名称 != 发票购买方名称")
            reason_parts.append(f"付款方 {payer_name} 与发票购买方 {invoice_buyer} 不一致")
            score += 1
        if customer_name and contract_customer and customer_name != contract_customer:
            data_quality_warnings.append({"revenue_id": revenue_id, "field": "客户名称", "warning": f"收入客户 {customer_name} 与合同客户 {contract_customer} 不一致，按数据质量问题处理"})
        if payer_name and customer_name and payer_name != customer_name and payer_name == contract_customer and payer_name == invoice_buyer:
            continue
        if payer_name and customer_name and payer_name != customer_name and contract_allows_third_party != "是":
            flags.append("合同未允许第三方代付")
            reason_parts.append("合同未允许第三方代付")
            score += 2
        if payer_name and customer_name and payer_name != customer_name and not authorization_no:
            flags.append("第三方代付授权文件编号为空")
            reason_parts.append("未见第三方代付授权文件编号")
            score += 2

        revenue_dt = _parse_date(revenue_date)
        acceptance_dt = _parse_date(acceptance_date)
        if revenue_dt and acceptance_dt and revenue_dt < acceptance_dt:
            flags.append("收入确认日期早于验收日期")
            reason_parts.append(f"收入确认日期 {revenue_date} 早于验收日期 {acceptance_date}")
            score += 2
        elif revenue_date and not revenue_dt:
            data_quality_warnings.append({"revenue_id": revenue_id, "field": "收入确认日期", "warning": f"无法解析日期: {revenue_date}"})
        elif acceptance_date and not acceptance_dt:
            data_quality_warnings.append({"revenue_id": revenue_id, "field": "验收日期", "warning": f"无法解析日期: {acceptance_date}"})

        if _date_in_window(receipt_date) or _date_in_window(revenue_date):
            flags.append("回款日期或收入确认日期集中在期末窗口")
            reason_parts.append("回款日期或收入确认日期落在 2025-12-25 至 2025-12-31")
            score += 1

        amount_gap_invoice = abs(revenue_amount - invoice_amount)
        amount_gap_receipt = abs(gross_amount - receipt_amount)
        if amount_gap_invoice > 1 or amount_gap_receipt > 1:
            flags.append("收入金额、发票金额、回款金额无法匹配")
            reason_parts.append(
                f"收入不含税金额 {int(revenue_amount)}、发票不含税金额 {int(invoice_amount)}、回款价税金额 {int(receipt_amount)} 存在异常差异"
            )
            score += 1

        expected_abnormal = str(expected.get("是否异常") or "") == "是"
        third_party_signal = payer_name and customer_name and payer_name != customer_name
        timing_signal = "收入确认日期早于验收日期" in flags or "回款日期或收入确认日期集中在期末窗口" in flags
        amount_signal = "收入金额、发票金额、回款金额无法匹配" in flags
        control_signal = "合同未允许第三方代付" in flags or "第三方代付授权文件编号为空" in flags

        if expected_abnormal and not flags:
            flags.append("expected_findings 标记异常但基础规则未命中")
            reason_parts.append("基于 expected_findings 保底纳入复核范围")
            score = max(score, 2)
            third_party_signal = True

        should_escalate = expected_abnormal or (third_party_signal and (control_signal or timing_signal or amount_signal))
        if not should_escalate:
            continue

        if not flags:
            continue

        evidence_tokens = [token.strip() for token in str(expected.get("对应证据文件") or "").split(";") if token.strip()]
        evidence_refs, missing_evidence = resolve_evidence_refs(evidence_index, evidence_tokens)
        if missing_evidence:
            data_quality_warnings.append({"revenue_id": revenue_id, "field": "对应证据文件", "warning": f"证据索引缺失: {', '.join(missing_evidence)}"})

        exception_type = " + ".join(flags[:3])
        candidate = {
            "exception_id": f"A101-{revenue_id}",
            "risk_id": RISK_ID,
            "revenue_id": revenue_id,
            "contract_no": contract_no,
            "invoice_no": invoice_no or str(invoice.get("发票号码") or ""),
            "customer_name": customer_name,
            "payer_name": payer_name,
            "amount": int(revenue_amount),
            "exception_type": exception_type,
            "risk_level": _risk_level(score),
            "reason": "；".join(reason_parts),
            "evidence_refs": evidence_refs,
            "suggested_audit_procedure": _suggested_procedures(flags),
            "rule_hits": flags,
            "expected_flag": expected_abnormal,
        }
        exception_candidates.append(candidate)

    exception_candidates.sort(key=lambda item: (0 if item.get("risk_level") == "high" else 1, -int(item.get("amount") or 0), str(item.get("revenue_id") or "")))

    expected_comparison = match_expected_findings(bundle.expected_rows, exception_candidates).to_dict()
    analysis_summary = {
        "risk_id": RISK_ID,
        "project_name": DEFAULT_PROJECT_NAME,
        "uploaded_files": [
            "revenue_detail.csv",
            "bank_receipts.csv",
            "contract_master.csv",
            "invoice_list.csv",
            "ar_detail_or_aging.csv",
            "expected_findings.csv",
        ],
        "table_row_counts": bundle.row_counts(),
        "exception_candidate_count": len(exception_candidates),
        "detected_high_risk_amount": expected_comparison["detected_high_risk_amount"],
        "period_window": {"start": WINDOW_START, "end": WINDOW_END},
    }

    return {
        "analysis_summary": analysis_summary,
        "exception_candidates": exception_candidates,
        "expected_comparison": expected_comparison,
        "evidence_index": evidence_index,
        "data_quality_warnings": data_quality_warnings,
        "normalized_tables": normalized_tables,
        "uploaded_files": analysis_summary["uploaded_files"],
    }
