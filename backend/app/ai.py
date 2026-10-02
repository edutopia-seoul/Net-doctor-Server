import json
import re
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .config import settings


class StructuredAI(BaseModel):
    model_config = ConfigDict(extra="ignore")
    severity: Literal["normal", "warning", "critical"] = "warning"
    primary_cause: str = "근거가 부족합니다."
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    measured_facts: list[str] = Field(default_factory=list)
    rule_findings: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    impact: str = "제공된 측정값만으로 영향 범위를 판단할 수 없습니다."
    recommendations: list[str] = Field(default_factory=list)
    additional_checks: list[str] = Field(default_factory=list)


RULE_ISSUES = {
    "INTERNET_UNREACHABLE": "인터넷 연결 불가", "GATEWAY_UNREACHABLE": "게이트웨이 연결 불가",
    "LOCAL_PACKET_LOSS": "게이트웨이 구간 패킷 손실", "EXTERNAL_PACKET_LOSS": "외부 구간 패킷 손실",
    "LOCAL_HIGH_LATENCY": "게이트웨이 지연", "EXTERNAL_HIGH_LATENCY": "인터넷 지연",
    "DNS_DELAY": "DNS 응답 지연", "TCP_RETRANSMISSION_HIGH": "TCP 재전송 증가",
    "HTTP_SERVER_RESPONSE_DELAY": "HTTP 서버 응답 지연", "INSUFFICIENT_DATA": "측정 데이터 부족",
}


def _rule_primary_cause(rules: dict) -> str:
    codes = rules.get("triggered_rules") or []
    return ("관측된 문제: " + ", ".join(RULE_ISSUES.get(code, code) for code in codes)
            if codes else "규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다.")


SYSTEM_PROMPT = """You are NetDoctor AI.
Use only supplied network measurements and rule-engine findings.
The supplied health_score is a read-only server calculation with deduction evidence.
You may explain its causes qualitatively. Never calculate, revise, invent, or return
health scores, category scores, weights, or deductions. They are not AI estimates.
Never invent measurements.
Clearly separate measured facts, rule-engine findings, and hypotheses.
If evidence is insufficient, state that additional measurement is required.
Do not claim certainty when multiple causes are possible.
Traceroute timeouts alone do not prove a path failure; routers may ignore probes.
If packet loss is zero and HTTP succeeds, do not claim the network is unreachable.
If no rule fired and available metrics are normal, describe a normal state.
An unresolved DNS collector or a zero timing is not evidence of DNS delay.
A resolved_ip is the queried site's address, not a configured DNS server.
Do not call DNS slow unless DNS_DELAY fired. Impact may describe possible user
effects of fired rules or collector errors, not introduce new metric faults.
Put unproven causes only in hypotheses. The server derives primary_cause from
rule findings, so do not generate primary_cause.
Do not put numbers or IP addresses in generated narrative text; exact values
already appear in server-supplied measured_facts and rule_findings.
Return only JSON with keys: severity, confidence, hypotheses, impact,
recommendations, additional_checks. The server adds primary_cause,
measured_facts, and rule_findings from trusted data; do not repeat them.
severity must be normal, warning, or critical. confidence must be LOW, MEDIUM, or HIGH.
Keep every array to at most 1 short item and each string to one short sentence.
Always return a non-null string for impact, including normal results.
Write all human-facing string values in Korean. Keep JSON keys, severity and
confidence enum values, metric names, rule codes, IP addresses, units, and
measured numbers unchanged. Never translate or alter measured values.
"""


def _json_from_text(text: str) -> dict:
    return json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I))


def _short_text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _text_list(value) -> list[str]:
    items = value if isinstance(value, list) else [value]
    texts = [_short_text(item).strip() for item in items if item is not None]
    return [item for item in texts if item.lower() not in ("", "null", "none")
            and re.search(r"[A-Za-z가-힣]", item) and not re.search(r"\d", item)]


def _measured_facts(measurement: dict) -> list[str]:
    facts = []
    for section, values in measurement.get("metrics", {}).items():
        if isinstance(values, dict):
            for key, value in values.items():
                if isinstance(value, (int, float, str)) and not isinstance(value, bool):
                    facts.append(f"{section}.{key}={value}")
    return facts


def analyze(measurement: dict, rules: dict, history: list[dict]) -> tuple[StructuredAI | None, str | None]:
    try:
        model_measurement = measurement.copy()
        model_measurement["metrics"] = measurement.get("metrics", {}).copy()
        traceroute = model_measurement["metrics"].get("traceroute")
        if isinstance(traceroute, dict):
            model_measurement["metrics"]["traceroute"] = {key: value for key, value in traceroute.items() if key != "hops"}
        response = httpx.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/chat",
            json={"model": settings.ollama_model, "stream": False, "think": False, "format": "json",
                  "options": {"num_predict": 320, "temperature": 0}, "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"measurement": model_measurement, "rule_engine": rules, "recent_history": history}, ensure_ascii=False)},
            ]}, timeout=120,
        )
        response.raise_for_status()
        raw = _json_from_text(response.json().get("message", {}).get("content", ""))
        for key in ("measured_facts", "rule_findings", "hypotheses", "recommendations", "additional_checks"):
            raw[key] = _text_list(raw.get(key, []))
        raw["measured_facts"] = _measured_facts(measurement)
        raw["rule_findings"] = rules["findings"]
        raw["primary_cause"] = _rule_primary_cause(rules)
        raw["impact"] = _short_text(raw["impact"]).strip() if raw.get("impact") is not None else ""
        if not raw["impact"]:
            raw["impact"] = ("현재 측정값에서는 사용자 영향이 확인되지 않았습니다." if rules.get("severity", raw.get("severity")) == "normal"
                             else "영향 범위를 판단하려면 추가 확인이 필요합니다.")
        if not raw["recommendations"]:
            raw["recommendations"] = (["현재 상태를 유지하며 주기적으로 다시 측정하세요."] if rules.get("severity", raw.get("severity")) == "normal"
                                      else ["관련 지표를 재측정하고 장비 상태를 확인하세요."])
        return StructuredAI.model_validate(raw), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
