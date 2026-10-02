import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import main
from app.ai import analyze
from app.config import settings
from app.db import Base, get_db
from app.models import Agent, HealthScore, Measurement
from app.score_store import stored_score
from app.scoring import load_score_config
from app.tools.backfill_health_scores import backfill, write_experiment_csv


NORMAL = json.loads((Path(__file__).parent / "fixtures/normal.json").read_text())


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Agent(agent_id="demo-agent", hostname="test", os="test", agent_version="test"))
        db.commit()
    yield engine
    engine.dispose()


def test_api_new_upload_fallback_history_and_auth(database, monkeypatch):
    def get_test_db():
        with Session(database) as db:
            yield db

    main.app.dependency_overrides[get_db] = get_test_db
    monkeypatch.setattr(settings, "agent_api_key", "test-key")
    sent = {}

    def no_ai(raw, rules, history):
        sent.update(raw)
        return None, "Ollama unavailable"

    monkeypatch.setattr(main, "analyze", no_ai)
    client = TestClient(main.app)
    headers = {"X-NetDoctor-Key": "test-key"}
    try:
        result = client.post("/api/v1/measurements", json=NORMAL, headers=headers)
        assert result.status_code == 200
        row = result.json()
        path = f"/api/v1/measurements/{row['id']}/health-score"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-NetDoctor-Key": "wrong"}).status_code == 401
        health = client.get(path, headers=headers).json()
        assert health == row["health_score"]
        assert health["overall"]["score"] == 100
        assert health["measurement_id"] == row["id"]
        assert sent["health_score"]["overall"]["score"] == 100
        assert client.get("/api/v1/measurements/999/health-score", headers=headers).status_code == 404
        history = client.get("/api/v1/agents/demo-agent/history", headers=headers).json()
        assert history[0]["health_score"] == health
        diagnosis = client.get(f"/api/v1/diagnoses/{row['id']}", headers=headers).json()
        assert diagnosis["measurement"]["health_score"] == health
        assert diagnosis["ai_diagnosis"]["available"] is False
        assert diagnosis["rule_diagnosis"]["severity"] == "normal"
    finally:
        main.app.dependency_overrides.clear()


def test_backfill_dry_run_persistence_repeat_and_config_conflict(database, tmp_path):
    config = load_score_config()
    with Session(database) as db:
        for identifier in range(21, 41):
            db.add(Measurement(id=identifier, agent_id="demo-agent", timestamp=datetime.now(timezone.utc),
                               metrics=NORMAL["metrics"], network=NORMAL["network"], collector_status=NORMAL["collector_status"]))
        db.commit()
        original = [(row.id, row.metrics, row.network, row.collector_status) for row in db.scalars(select(Measurement)).all()]
        results, inserted = backfill(db, config, 21, 40, "demo-agent")
        assert inserted == 0 and len(results) == 20
        assert db.scalar(select(func.count()).select_from(HealthScore)) == 0
        results, inserted = backfill(db, config, 21, 40, "demo-agent", apply=True)
        assert inserted == 20
        db.commit()
    with Session(database) as db:
        results, inserted = backfill(db, config, 21, 40, "demo-agent", apply=True)
        assert inserted == 0
        assert db.scalar(select(func.count()).select_from(HealthScore)) == 20
        assert [(row.id, row.metrics, row.network, row.collector_status) for row in db.scalars(select(Measurement)).all()] == original
        assert stored_score(db.get(Measurement, 22), config.score_version).overall.score == 100
        row = db.scalar(select(HealthScore))
        assert row.config_snapshot == config.model_dump()
        modified = config.model_copy(update={"tcp_min_packets": 99})
        with pytest.raises(ValueError, match="score_version"):
            backfill(db, modified, 21, 40, "demo-agent", apply=True)
        summary = write_experiment_csv(results, tmp_path / "health_score_experiment.csv")
        assert len(summary) == 4 and all(item["overall"] == 100 for item in summary)
        assert len((tmp_path / "health_score_representatives.csv").read_text().splitlines()) == 5
        assert b"\r" not in (tmp_path / "health_score_experiment.csv").read_bytes()
        next_version = modified.model_copy(update={"score_version": "health-score-v2"})
        _, inserted = backfill(db, next_version, 21, 40, "demo-agent", apply=True)
        db.commit()
        assert inserted == 20 and db.scalar(select(func.count()).select_from(HealthScore)) == 40
        assert stored_score(db.get(Measurement, 22), config.score_version).config_hash == results[1].config_hash


@pytest.mark.parametrize("start,end,agent", [(21, 23, "demo-agent"), (22, 22, "wrong-agent"), (22, 21, "demo-agent")])
def test_backfill_rejects_bad_scope(database, start, end, agent):
    with Session(database) as db:
        db.add(Measurement(id=22, agent_id="demo-agent", timestamp=datetime.now(timezone.utc), metrics=NORMAL["metrics"]))
        db.commit()
        with pytest.raises(ValueError):
            backfill(db, load_score_config(), start, end, agent, apply=True)
        assert db.scalar(select(func.count()).select_from(HealthScore)) == 0


def test_ai_receives_read_only_score_and_cannot_replace_it(monkeypatch):
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"severity":"normal","health_score":999,"confidence":"LOW"}'}}

    def post(*args, **kwargs):
        sent.update(kwargs["json"])
        return Response()

    monkeypatch.setattr("app.ai.httpx.post", post)
    raw = NORMAL | {"health_score": {"overall": {"score": 70}, "main_deductions": []}}
    result, error = analyze(raw, {"findings": [], "severity": "normal"}, [])
    assert error is None and "health_score" not in result.model_dump()
    assert json.loads(sent["messages"][1]["content"])["measurement"]["health_score"]["overall"]["score"] == 70
    assert "Never calculate, revise" in sent["messages"][0]["content"]
    assert raw["health_score"]["overall"]["score"] == 70
