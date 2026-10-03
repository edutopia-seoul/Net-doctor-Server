import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.scoring import ScoreConfig, calculate_score, config_hash, load_score_config


NORMAL = json.loads((Path(__file__).parent / "fixtures/normal.json").read_text())
V11 = Path(__file__).parents[1] / "app" / "health_score_v1_1.yaml"


def score(metrics=None, rules=None):
    payload = copy.deepcopy(NORMAL)
    for section, values in (metrics or {}).items():
        payload["metrics"][section] = {**(payload["metrics"].get(section) or {}), **values}
    return calculate_score(payload, load_score_config(str(V11)), rule_diagnosis=rules)


def test_v11_status_guard_protects_high_weighted_score():
    result = score({"gateway_ping": {"avg_rtt_ms": 102, "packet_loss_pct": 10}},
                   {"severity": "normal", "triggered_rules": []})
    assert result.overall.score > 80
    assert result.overall.base_severity == "normal"
    assert result.overall.severity == "warning"
    assert result.overall.status == "warning"
    assert "critical_category" in result.overall.guard_triggered
    assert result.categories["local"].score < 40


def test_rule_warning_guard_applies_even_when_score_is_high():
    result = score(rules={"severity": "warning", "triggered_rules": ["LOCAL_PACKET_LOSS"]})
    assert result.overall.score == 100
    assert result.overall.base_severity == "normal"
    assert result.overall.status == "warning"
    assert "rule_warning" in result.overall.guard_triggered


def test_linear_boundary_has_no_step_jump():
    before = score({"http": {"ttfb_ms": 799}})
    after = score({"http": {"ttfb_ms": 801}})
    before_points = before.categories["http"].deductions[0].points
    after_points = after.categories["http"].deductions[0].points
    assert 0 < before_points < 25
    assert 25 < after_points < 26
    assert abs(after_points - before_points) < 1


def test_rst_alone_is_not_a_transport_fault():
    result = score({"tcp": {"rst": 1, "retransmission_pct": 0, "duplicate_ack": 0, "zero_window": 0}})
    assert not any(item.code == "TCP_RST_OBSERVED" for item in result.categories["tcp"].deductions)
    assert any("RST" in note for note in result.categories["tcp"].notes)


def test_tcp_quality_exposes_low_sample_and_sample_size():
    result = score({"tcp": {"captured_packets": 36, "retransmission_pct": 8.333}})
    tcp = result.categories["tcp"]
    assert tcp.sample_size == 36
    assert tcp.quality == "low_sample"
    assert result.overall.quality == "low_confidence"


def test_v11_hash_canonicalizes_integer_and_float_zero():
    config = load_score_config(str(V11))
    raw = config.model_dump()
    raw["categories"]["local"]["metrics"]["gateway_ping.avg_rtt_ms"]["minimum"] = 0
    raw["categories"]["internet"]["metrics"]["internet_ping.avg_rtt_ms"]["minimum"] = 0
    equivalent = config.__class__.model_validate(raw)
    assert config_hash(config) == config_hash(equivalent)


def test_legacy_policy_hash_still_matches_stored_v1():
    config = load_score_config()
    assert config_hash(config) == "c64ff81ece540b6c0e8433f979e9422c13a40e2260793a62bc995368ab10df18"
    assert config_hash(ScoreConfig.model_validate(config.model_dump())) == config_hash(config)
    assert calculate_score(NORMAL, config).overall.score == 100
    for feature in ("linear", "guard", "rst", "cause_group"):
        raw = config.model_dump()
        if feature == "linear":
            raw["categories"]["local"]["metrics"]["gateway_ping.avg_rtt_ms"]["linear_start"] = 10
        elif feature == "guard":
            raw["severity_guard"] = load_score_config(str(V11)).severity_guard.model_dump()
        elif feature == "rst":
            raw["rst_support_thresholds"] = {"tcp.retransmission_pct": 5}
        else:
            raw["categories"]["local"]["metrics"]["gateway_ping.avg_rtt_ms"]["cause_group"] = "LATENCY"
        with pytest.raises(ValidationError, match="new score_version"):
            ScoreConfig.model_validate(raw)


@pytest.mark.parametrize("path", ["gateway_ping.avg_rtt_ms", "internet_ping.avg_rtt_ms",
                                "gateway_ping.packet_loss_pct", "internet_ping.packet_loss_pct",
                                "tcp.retransmission_pct", "http.ttfb_ms"])
def test_every_linear_anchor_is_continuous_monotonic_and_capped(path):
    section, field = path.split(".")
    config = load_score_config(str(V11))
    category = next(name for name, policy in config.categories.items() if path in policy.metrics)
    policy = config.categories[category].metrics[path]
    def deduction(value):
        result = score({section: {field: value}})
        return sum(d.points for d in result.categories[category].deductions if d.metric == path)
    for anchor in [policy.linear_start] + [b.threshold for b in policy.bands]:
        samples = [max(0, anchor - .0001), anchor, min(policy.maximum or float('inf'), anchor + .0001)]
        points = [deduction(v) for v in samples]
        assert points == sorted(points)
        assert max(points) - min(points) < .02
    assert deduction(policy.linear_start) == 0
    assert deduction(policy.bands[-1].threshold) == policy.bands[-1].points


def test_critical_rule_guard_does_not_change_numeric_score():
    base = score(rules={"severity": "normal"})
    guarded = score(rules={"severity": "critical", "triggered_rules": ["GATEWAY_UNREACHABLE"]})
    assert guarded.overall.score == base.overall.score == 100
    assert guarded.overall.status == "critical"
    assert guarded.overall.guard_triggered == ["rule_critical"]


def test_rst_requires_repetition_and_correlated_evidence():
    for rst, retrans, expected in [(1, 8, False), (5, 0, False), (5, 8, True)]:
        tcp = score({"tcp": {"rst": rst, "duplicate_ack": 0, "zero_window": 0, "retransmission_pct": retrans}}).categories['tcp']
        assert any(d.code == 'TCP_RST_OBSERVED' for d in tcp.deductions) is expected


def test_partial_coverage_and_unavailable_reweighting_are_distinct():
    result = score({"dns": {"system_ms": None, "google_ms": 65, "cloudflare_ms": None},
                    "tcp": {"captured_packets": 36}})
    assert result.categories['dns'].score == 100
    assert result.categories['dns'].coverage == .3333
    assert result.overall.coverage == .9
    assert result.overall.included_weight == 1
    absent = calculate_score({'metrics': {'gateway_ping': NORMAL['metrics']['gateway_ping'],
                                        'internet_ping': NORMAL['metrics']['internet_ping'],
                                        'http': NORMAL['metrics']['http']}}, load_score_config(str(V11)))
    assert absent.categories['dns'].score is None and absent.categories['tcp'].score is None
    assert absent.overall.included_weight == .65 and absent.overall.score == 100
    empty = calculate_score({'metrics': {}}, load_score_config(str(V11)))
    assert empty.overall.score is None and empty.overall.quality == 'unavailable'


def test_v11_hash_stable_for_key_order_and_numeric_notation_but_not_policy_change():
    cfg = load_score_config(str(V11))
    raw = json.loads(json.dumps(cfg.model_dump()), parse_int=float)
    # Integer-typed fields are validated back to integers; all float fields canonicalize.
    reordered = ScoreConfig.model_validate(dict(reversed(list(raw.items()))))
    assert config_hash(cfg) == config_hash(reordered)
    changed = cfg.model_copy(update={'tcp_min_packets': 51})
    assert config_hash(cfg) != config_hash(changed)


def test_invalid_linear_start_rejected():
    raw = load_score_config(str(V11)).model_dump()
    raw['categories']['http']['metrics']['http.ttfb_ms']['linear_start'] = 800
    with pytest.raises(ValidationError, match='linear_start'):
        ScoreConfig.model_validate(raw)


def test_cause_groups_and_fractional_deduction_trace():
    result = score({'gateway_ping': {'avg_rtt_ms': 202.9, 'packet_loss_pct': 10},
                    'internet_ping': {'avg_rtt_ms': 202.9}, 'http': {'ttfb_ms': 809.733}})
    assert {'LATENCY', 'LATENCY_EFFECT', 'PACKET_LOSS'} <= {c.cause_group for c in result.top_causes}
    for c in result.categories.values():
        assert c.score == pytest.approx(100 - sum(d.points for d in c.deductions))
    assert 100-result.overall.score == pytest.approx(sum(c.weighted_points for c in result.top_causes), abs=.006)


def test_non_linear_metrics_keep_step_behavior():
    result = score({'http': {'status_code': 200}, 'dns': {'system_ms': 299},
                    'tcp': {'duplicate_ack': 1, 'zero_window': 0, 'retransmission_pct': 0}})
    assert not result.categories['dns'].deductions
    assert not result.categories['http'].deductions
    assert not result.categories['tcp'].deductions


def test_versions_coexist_backfill_is_idempotent_and_comparison_is_read_only(tmp_path):
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session
    from app.db import Base
    from app.models import Agent, HealthScore, Measurement, RuleDiagnosis
    from app.score_store import stored_score
    from app.tools.backfill_health_scores import backfill, write_comparison_csv
    engine = create_engine(f"sqlite:///{tmp_path / 'version.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Agent(agent_id='demo-agent', hostname='test', os='test', agent_version='test'))
        for mid in range(21, 41):
            raw = copy.deepcopy(NORMAL['metrics'])
            if mid == 38:
                raw['gateway_ping'].update(avg_rtt_ms=102.889, packet_loss_pct=10)
            db.add(Measurement(id=mid, agent_id='demo-agent', timestamp=datetime.now(timezone.utc), metrics=raw,
                               network=NORMAL['network'], collector_status=NORMAL['collector_status']))
            db.add(RuleDiagnosis(measurement_id=mid, severity='warning' if mid == 38 else 'normal',
                                 triggered_rules=['LOCAL_PACKET_LOSS', 'LOCAL_HIGH_LATENCY'] if mid == 38 else [], findings=[]))
        db.commit()
        v1 = load_score_config()
        v11 = load_score_config(str(V11))
        backfill(db, v1, 21, 40, 'demo-agent', apply=True)
        db.commit()
        original = [(r.measurement_id, r.config_snapshot, r.config_hash, r.result) for r in db.scalars(select(HealthScore)).all()]
        preview, inserted = backfill(db, v11, 21, 40, 'demo-agent')
        assert len(preview) == 20 and inserted == 0
        assert db.scalar(select(func.count()).select_from(HealthScore)) == 20
        results, inserted = backfill(db, v11, 21, 40, 'demo-agent', apply=True)
        assert inserted == 20
        db.commit()
        assert backfill(db, v11, 21, 40, 'demo-agent', apply=True)[1] == 0
        assert db.scalar(select(func.count()).select_from(HealthScore)) == 40
        assert [(r.measurement_id, r.config_snapshot, r.config_hash, r.result) for r in db.scalars(select(HealthScore).where(HealthScore.score_version == v1.score_version)).all()] == original
        old, new = stored_score(db.get(Measurement, 38), v1.score_version), stored_score(db.get(Measurement, 38), v11.score_version)
        assert old.overall.score == 83 and old.overall.severity == 'normal'
        assert new.overall.score > 80 and new.overall.base_severity == 'normal'
        assert new.overall.status == 'warning'
        exported = write_comparison_csv(db, results, tmp_path/'comparison.csv')
        assert len(exported) == 20 and exported[17]['v1_1_final_status'] == 'warning'
        assert b'\r' not in (tmp_path/'comparison.csv').read_bytes()
        with pytest.raises(ValueError, match='preserved'):
            write_comparison_csv(db, results, tmp_path/'health_score_experiment.csv')
        with pytest.raises(ValueError, match='score_version'):
            backfill(db, v11.model_copy(update={'tcp_min_packets': 51}), 21, 40, 'demo-agent', apply=True)
    engine.dispose()


def test_guard_backfill_rejects_missing_rules_before_any_write(tmp_path):
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session
    from app.db import Base
    from app.models import Agent, HealthScore, Measurement
    from app.tools.backfill_health_scores import backfill
    engine = create_engine(f"sqlite:///{tmp_path / 'missing-rule.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Agent(agent_id='demo-agent', hostname='test', os='test', agent_version='test'))
        db.add(Measurement(id=22, agent_id='demo-agent', timestamp=datetime.now(timezone.utc), metrics=NORMAL['metrics']))
        db.commit()
        with pytest.raises(ValueError, match='Rule Diagnosis'):
            backfill(db, load_score_config(str(V11)), 22, 22, 'demo-agent', apply=True)
        assert db.scalar(select(func.count()).select_from(HealthScore)) == 0
    engine.dispose()


def test_version_api_history_new_upload_and_ai_fallback(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app import main
    from app.config import settings
    from app.db import Base, get_db
    from app.models import Agent, Measurement
    from app.score_store import store_score
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Agent(agent_id='demo-agent', hostname='test', os='test', agent_version='test'))
        db.commit()
    def get_test_db():
        with Session(engine) as db:
            yield db
    sent = {}
    def unavailable(raw, rules, history):
        sent.update(raw['health_score'])
        return None, 'Ollama unavailable'
    monkeypatch.setattr(settings, 'health_score_path', str(V11))
    monkeypatch.setattr(settings, 'agent_api_key', 'test-key')
    monkeypatch.setattr(main, 'analyze', unavailable)
    main.app.dependency_overrides[get_db] = get_test_db
    try:
        client = TestClient(main.app)
        headers = {'X-NetDoctor-Key': 'test-key'}
        raw = copy.deepcopy(NORMAL)
        raw['metrics']['gateway_ping']['avg_rtt_ms'] = 21
        response = client.post('/api/v1/measurements', json=raw, headers=headers)
        assert response.status_code == 200
        mid = response.json()['id']
        path = f'/api/v1/measurements/{mid}/health-score'
        new = response.json()['health_score']
        assert new['overall']['score'] > 80 and new['overall']['status'] == 'warning'
        assert 'rule_warning' in new['overall']['guard_triggered']
        assert sent['overall']['status'] == 'warning'
        assert sent['overall']['guard_reason']
        assert client.get(path).status_code == 401
        assert client.get(path+'?score_version=health-score-v1', headers=headers).status_code == 404
        with Session(engine) as db:
            store_score(db, db.get(Measurement, mid), load_score_config())
            db.commit()
        old = client.get(path+'?score_version=health-score-v1', headers=headers).json()
        assert old['score_version'] == 'health-score-v1'
        assert client.get(path, headers=headers).json() == new
        assert client.get(path+'?score_version=unknown', headers=headers).status_code == 404
        for version in ('health-score-v1', 'health-score-v1.1'):
            for endpoint in [f'/measurements/{mid}', f'/diagnoses/{mid}']:
                data = client.get('/api/v1'+endpoint+'?score_version='+version, headers=headers).json()
                measurement = data.get('measurement', data)
                assert measurement['health_score']['score_version'] == version
            history = client.get('/api/v1/agents/demo-agent/history?score_version='+version, headers=headers).json()
            assert history[0]['health_score']['score_version'] == version
        diagnostic = client.get(f'/api/v1/diagnoses/{mid}', headers=headers).json()
        assert not diagnostic['ai_diagnosis']['available']
        assert diagnostic['rule_diagnosis']['severity'] == 'warning'
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
