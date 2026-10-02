import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.scoring import ScoreConfig, calculate_score, load_score_config


NORMAL = json.loads((Path(__file__).parent / "fixtures/normal.json").read_text())


def score(metrics=None, collector_status=None):
    payload = copy.deepcopy(NORMAL)
    if metrics:
        for section, values in metrics.items():
            if values is None:
                payload["metrics"][section] = None
            else:
                payload["metrics"][section] = {**(payload["metrics"].get(section) or {}), **values}
    if collector_status is not None:
        payload["collector_status"] = collector_status
    return calculate_score(payload, load_score_config())


def test_normal_score_is_complete_and_explainable():
    result = score()
    assert result.overall.score == 100
    assert result.overall.severity == "normal"
    assert all(category.score == 100 and not category.deductions for category in result.categories.values())


@pytest.mark.parametrize("changes,category", [
    ({"gateway_ping": {"avg_rtt_ms": 203}, "internet_ping": {"avg_rtt_ms": 203}}, "local"),
    ({"internet_ping": {"packet_loss_pct": 10}, "tcp": {"retransmission_pct": 8.3}}, "internet"),
    ({"gateway_ping": {"avg_rtt_ms": 103, "packet_loss_pct": 10},
      "internet_ping": {"avg_rtt_ms": 104, "packet_loss_pct": 10}}, "local"),
])
def test_faults_reduce_corresponding_categories(changes, category):
    result = score(changes)
    assert result.categories[category].score < 100
    assert 0 < result.overall.score < 100
    for item in result.categories.values():
        assert 0 <= item.score <= 100
        assert item.score == 100 - sum(d.points for d in item.deductions)
        for deduction in item.deductions:
            assert deduction.metric and deduction.reason and deduction.value >= 0


def test_unreachable_and_large_penalties_stay_in_range():
    result = score({"gateway_ping": {"packet_loss_pct": 100, "avg_rtt_ms": 999},
                    "internet_ping": {"packet_loss_pct": 100, "avg_rtt_ms": 999},
                    "tcp": {"retransmission_pct": 100, "duplicate_ack": 100, "rst": 100, "zero_window": 100},
                    "http": {"status_code": 503, "ttfb_ms": 9999}})
    for item in result.categories.values():
        assert 0 <= item.score <= 100
        assert item.score == 100 - sum(d.points for d in item.deductions)
    assert result.categories["local"].score == result.categories["internet"].score == 0
    assert result.overall.severity == "critical"


@pytest.mark.parametrize("weights", [
    {"local": .2, "internet": .25, "dns": .15, "tcp": .2, "http": .3},
    {"local": -.2, "internet": .65, "dns": .15, "tcp": .2, "http": .2},
    {"local": 1},
])
def test_weight_config_rejected(weights):
    config = load_score_config().model_dump()
    config["weights"] = weights
    with pytest.raises(ValidationError):
        ScoreConfig.model_validate(config)


def test_bands_and_severity_config_rejected():
    config = load_score_config().model_dump()
    config["categories"]["local"]["metrics"]["gateway_ping.avg_rtt_ms"]["bands"][1]["threshold"] = 1
    with pytest.raises(ValidationError):
        ScoreConfig.model_validate(config)
    config = load_score_config().model_dump()
    config["severity"]["warning_min"] = 90
    with pytest.raises(ValidationError):
        ScoreConfig.model_validate(config)


def test_missing_dns_and_tcp_are_not_full_scores():
    result = score({"dns": None, "tcp": None})
    assert result.categories["dns"].score is None
    assert result.categories["tcp"].available is False
    assert result.overall.coverage < 1 and result.overall.quality == "partial"
    assert result.overall.included_weight == pytest.approx(.65)
    empty = calculate_score({"metrics": {}}, load_score_config())
    assert empty.overall.score is None and not empty.overall.available


def test_dns_partial_is_coverage_not_performance_penalty():
    result = score({"dns": {"cloudflare_ms": None}}, [{"name": "dns", "status": "partial", "message": "resolver failed"}])
    dns = result.categories["dns"]
    assert dns.score == 100 and dns.available
    assert dns.coverage == pytest.approx(2 / 3, abs=.0001)
    assert dns.quality == "partial" and dns.notes
    result = score({"dns": {"system_ms": None, "cloudflare_ms": None}})
    assert result.categories["dns"].coverage == pytest.approx(1 / 3, abs=.0001)
    assert "dns.system_ms" in result.categories["dns"].missing_metrics


def test_low_tcp_sample_and_double_deductions():
    result = score({"tcp": {"captured_packets": 30, "retransmission_pct": 10, "duplicate_ack": 20},
                    "http": {"ttfb_ms": 1600, "total_ms": 5000, "connect_ms": 1800, "tls_ms": 3500}})
    assert result.categories["tcp"].low_sample and result.categories["tcp"].quality == "partial"
    assert len([d for d in result.categories["tcp"].deductions if d.group == "transmission"]) == 1
    assert len(result.categories["http"].deductions) == 1
    assert result.categories["http"].score == 60


def test_zero_capture_does_not_establish_zero_tcp_errors():
    result = score({"tcp": {"captured_packets": 0, "retransmission_pct": 0}})
    assert result.categories["tcp"].score is None
    assert not result.categories["tcp"].available
    assert result.categories["tcp"].low_sample


@pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf"), True, "200"])
def test_invalid_metric_is_not_zero_or_normal(value):
    result = score({"internet_ping": {"avg_rtt_ms": value, "packet_loss_pct": None}})
    assert result.categories["internet"].score is None


def test_severity_boundaries():
    config = load_score_config()
    from app.scoring import score_severity
    assert [score_severity(value, config) for value in [100, 80, 79, 60, 59, 0, None]] == [
        "normal", "normal", "warning", "warning", "critical", "critical", "unknown"]
