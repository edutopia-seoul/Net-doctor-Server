import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import StructuredAI, _measured_facts, analyze
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app import main


FIXTURES = Path(__file__).parent / "fixtures"


def test_api_flow(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    monkeypatch.setattr(settings, "agent_api_key", "test-key")
    monkeypatch.setattr(main, "analyze", lambda raw, rules, history: (
        StructuredAI(severity=rules["severity"], primary_cause="See rule evidence", confidence="LOW",
                     measured_facts=_measured_facts(raw), rule_findings=rules["findings"]), None))
    client = TestClient(app)
    headers = {"X-NetDoctor-Key": "test-key"}
    try:
        assert client.get("/api/v1/agents").status_code == 401
        assert client.get("/api/v1/agents", headers={"X-NetDoctor-Key": "wrong"}).status_code == 401
        assert client.post("/api/v1/agents/register", headers=headers, json={
            "agent_id": "demo-agent", "hostname": "demo", "os": "Ubuntu 24.04 LTS", "agent_version": "0.1.0"}).status_code == 200
        expected = {
            "normal.json": [], "gateway_failure.json": ["GATEWAY_UNREACHABLE"],
            "packet_loss.json": ["EXTERNAL_PACKET_LOSS"], "dns_delay.json": ["DNS_DELAY"],
            "tcp_retransmission.json": ["TCP_RETRANSMISSION_HIGH"],
            "server_delay.json": ["HTTP_SERVER_RESPONSE_DELAY"],
        }
        for filename, rules in expected.items():
            payload = json.loads((FIXTURES / filename).read_text())
            response = client.post("/api/v1/measurements", headers=headers, json=payload)
            assert response.status_code == 200, response.text
            diagnosis = client.get(f"/api/v1/diagnoses/{response.json()['id']}", headers=headers).json()
            assert diagnosis["rule_diagnosis"]["triggered_rules"] == rules
            assert diagnosis["ai_diagnosis"]["available"] is True
        invalid = json.loads((FIXTURES / "normal.json").read_text())
        invalid["schema_version"] = "2.0"
        assert client.post("/api/v1/measurements", headers=headers, json=invalid).status_code == 422
        assert len(client.get("/api/v1/agents/demo-agent/history", headers=headers).json()) == 6
        latest = client.get("/api/v1/agents/demo-agent/history?limit=2", headers=headers).json()
        assert [item["timestamp"] for item in latest] == ["2026-09-28T06:04:00", "2026-09-28T06:05:00"]
        monkeypatch.setattr(main, "analyze", lambda *_: (None, "unavailable"))
        response = client.post("/api/v1/measurements", headers=headers, json=invalid | {"schema_version": "1.0"})
        assert response.status_code == 200
        diagnosis = client.get(f"/api/v1/diagnoses/{response.json()['id']}", headers=headers).json()
        assert diagnosis["ai_diagnosis"]["available"] is False
        assert diagnosis["rule_diagnosis"]["severity"] == "normal"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_measured_facts_ignore_model_claims():
    assert _measured_facts({"metrics": {"dns": {"system_ms": 25, "resolved_ip": "1.1.1.1", "missing": None}}}) == [
        "dns.system_ms=25", "dns.resolved_ip=1.1.1.1"]


def test_ai_output_uses_server_evidence(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": json.dumps({"severity": "warning", "confidence": "MEDIUM",
                "primary_cause": "possible DNS delay", "measured_facts": ["invented 999 ms"],
                "rule_findings": ["invented rule"], "hypotheses": [], "impact": "slow browsing",
                "recommendations": [], "additional_checks": []})}}

    monkeypatch.setattr("app.ai.httpx.post", lambda *args, **kwargs: Response())
    result, error = analyze({"metrics": {"dns": {"system_ms": 500}}},
                            {"findings": ["DNS system_ms response is 500 ms"]}, [])
    assert error is None
    assert result.measured_facts == ["dns.system_ms=500"]
    assert result.rule_findings == ["DNS system_ms response is 500 ms"]


def test_ai_normal_result_accepts_null_descriptions(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": json.dumps({"severity": "normal", "confidence": "LOW",
                "primary_cause": None, "impact": None})}}

    monkeypatch.setattr("app.ai.httpx.post", lambda *args, **kwargs: Response())
    result, error = analyze({"metrics": {}}, {"findings": []}, [])
    assert error is None
    assert result.severity == "normal"
    assert result.primary_cause == "규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다."
    assert result.impact == "현재 측정값에서는 사용자 영향이 확인되지 않았습니다."
    assert result.recommendations == ["현재 상태를 유지하며 주기적으로 다시 측정하세요."]


def test_ai_prompt_omits_ambiguous_traceroute_hops_but_preserves_facts(monkeypatch):
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"severity":"normal","primary_cause":"정상","confidence":"LOW"}'}}

    def post(*args, **kwargs):
        sent.update(kwargs["json"])
        return Response()

    monkeypatch.setattr("app.ai.httpx.post", post)
    measurement = {"metrics": {"traceroute": {"hop_count": 12, "hops": [{"hop": 2, "timeout": True}]}}}
    result, error = analyze(measurement, {"findings": []}, [])
    assert error is None
    assert "hops" not in json.loads(sent["messages"][1]["content"])["measurement"]["metrics"]["traceroute"]
    assert measurement["metrics"]["traceroute"]["hops"] == [{"hop": 2, "timeout": True}]
    assert result.measured_facts == ["traceroute.hop_count=12"]


def test_ai_discards_untrusted_numeric_and_broken_list_items(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": json.dumps({"severity": "normal", "primary_cause": "정상",
                "hypotheses": ["DNS 서버가 172.66.x.x로 변경됨", "일시적 현상일 수 있음"],
                "recommendations": [None, "측정을 반복하세요"], "additional_checks": ["]} }", "null"]})}}

    monkeypatch.setattr("app.ai.httpx.post", lambda *args, **kwargs: Response())
    result, error = analyze({"metrics": {}}, {"findings": []}, [])
    assert error is None
    assert result.hypotheses == ["일시적 현상일 수 있음"]
    assert result.recommendations == ["측정을 반복하세요"]
    assert result.additional_checks == []


def test_ai_primary_cause_is_anchored_to_rules(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": json.dumps({"severity": "warning", "confidence": "HIGH",
                "primary_cause": "증거 없는 DNS 서버 고장", "hypotheses": ["추가 확인 필요"]})}}

    monkeypatch.setattr("app.ai.httpx.post", lambda *args, **kwargs: Response())
    result, error = analyze({"metrics": {}}, {"findings": ["gateway packet loss is 20%"],
                             "triggered_rules": ["LOCAL_PACKET_LOSS"]}, [])
    assert error is None
    assert result.primary_cause == "관측된 문제: 게이트웨이 구간 패킷 손실"
