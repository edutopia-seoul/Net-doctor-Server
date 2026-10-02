from pathlib import Path

import pytest

from app.rule_engine import diagnose

RULES = str(Path(__file__).parents[1] / "app" / "rules.yaml")


def test_gateway_failure():
    result = diagnose({"gateway_ping": {"packet_loss_pct": 100}}, RULES)
    assert "GATEWAY_UNREACHABLE" in result["triggered_rules"]
    assert result["severity"] == "critical"


def test_multiple_rules_keep_evidence():
    result = diagnose({"internet_ping": {"avg_rtt_ms": 200, "packet_loss_pct": 5}, "dns": {"system_ms": 500}}, RULES)
    assert {"EXTERNAL_PACKET_LOSS", "EXTERNAL_HIGH_LATENCY", "DNS_DELAY"} <= set(result["triggered_rules"])
    assert len(result["findings"]) == 3


def test_insufficient_data():
    assert diagnose({}, RULES)["triggered_rules"] == ["INSUFFICIENT_DATA"]
    assert diagnose({"gateway_ping": {"avg_rtt_ms": None, "packet_loss_pct": None}}, RULES)["triggered_rules"] == ["INSUFFICIENT_DATA"]


@pytest.mark.parametrize("metrics,rule", [
    ({"internet_ping": {"packet_loss_pct": 100}}, "INTERNET_UNREACHABLE"),
    ({"gateway_ping": {"packet_loss_pct": 4}}, "LOCAL_PACKET_LOSS"),
    ({"internet_ping": {"avg_rtt_ms": 151}}, "EXTERNAL_HIGH_LATENCY"),
    ({"tcp": {"retransmission_pct": 5}}, "TCP_RETRANSMISSION_HIGH"),
    ({"http": {"ttfb_ms": 801}}, "HTTP_SERVER_RESPONSE_DELAY"),
])
def test_each_threshold_keeps_evidence(metrics, rule):
    result = diagnose(metrics, RULES)
    assert rule in result["triggered_rules"]
    assert result["findings"]
