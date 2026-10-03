"""Deterministic quality scores; missing collectors are not invented performance faults."""
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import CategoryScore, HealthScoreOut, OverallScore, ScoreCause, ScoreDeduction


CATEGORIES = {"local", "internet", "dns", "tcp", "http"}


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Band(ConfigModel):
    threshold: float = Field(ge=0)
    points: int = Field(gt=0, le=100)


class MetricPolicy(ConfigModel):
    code: str = Field(min_length=1)
    unit: str
    operator: Literal["ge", "gt"] = "ge"
    group: str | None = None
    cause_group: str = "UNSPECIFIED"
    linear_start: float | None = Field(default=None, ge=0)
    minimum: float = Field(default=0, ge=0)
    maximum: float | None = Field(default=None, ge=0)
    integer: bool = False
    bands: list[Band] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_bands(self):
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("metric range is invalid")
        if any(a.threshold >= b.threshold or a.points > b.points for a, b in zip(self.bands, self.bands[1:])):
            raise ValueError("bands must have increasing thresholds and nondecreasing deductions")
        if any(b.threshold < self.minimum or (self.maximum is not None and b.threshold > self.maximum) for b in self.bands):
            raise ValueError("threshold is outside metric range")
        if self.linear_start is not None and not self.minimum <= self.linear_start < self.bands[0].threshold:
            raise ValueError("linear_start must precede first anchor within metric range")
        return self


class CategoryPolicy(ConfigModel):
    collectors: list[str] = Field(default_factory=list)
    metrics: dict[str, MetricPolicy] = Field(min_length=1)


class SeverityPolicy(ConfigModel):
    normal_min: float = Field(ge=0, le=100)
    warning_min: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def ordered_levels(self):
        if self.warning_min >= self.normal_min:
            raise ValueError("warning_min must be below normal_min")
        return self


class SeverityGuard(ConfigModel):
    critical_category_threshold: float = Field(ge=0, le=100)
    warning_category_threshold: float = Field(ge=0, le=100)
    critical_category_forces_at_least: Literal["normal", "warning", "critical"]
    warning_category_forces_at_least: Literal["normal", "warning", "critical"]
    rule_warning_forces_at_least: Literal["normal", "warning", "critical"]
    rule_critical_forces: Literal["warning", "critical"]

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if self.critical_category_threshold > self.warning_category_threshold:
            raise ValueError("critical category threshold must not exceed warning threshold")
        return self


class ScoreConfig(ConfigModel):
    score_version: str = Field(min_length=1, max_length=64)
    weights: dict[str, float]
    severity: SeverityPolicy
    minimum_available_weight: float = Field(gt=0, le=1)
    tcp_min_packets: int = Field(gt=0)
    categories: dict[str, CategoryPolicy]
    severity_guard: SeverityGuard | None = None
    rst_support_thresholds: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_weights(self):
        if set(self.weights) != CATEGORIES or set(self.categories) != CATEGORIES:
            raise ValueError("exactly five category policies/weights are required")
        if any(not math.isfinite(w) or w <= 0 for w in self.weights.values()) or not math.isclose(sum(self.weights.values()), 1, abs_tol=1e-9):
            raise ValueError("positive finite weights must sum to 1.0")
        for category in self.categories.values():
            if any(path.count(".") != 1 for path in category.metrics):
                raise ValueError("metric paths must be section.field")
        if self.score_version == "health-score-v1" and (
            self.severity_guard is not None or self.rst_support_thresholds
            or any(policy.linear_start is not None or policy.cause_group != "UNSPECIFIED"
                   for category in self.categories.values() for policy in category.metrics.values())
        ):
            raise ValueError("v1 legacy hash cannot cover new policy features; use a new score_version")
        if any(path not in self.categories["tcp"].metrics or not math.isfinite(value) or value <= 0
               for path, value in self.rst_support_thresholds.items()):
            raise ValueError("RST support must reference TCP metrics with positive finite thresholds")
        return self


@lru_cache(maxsize=4)
def load_score_config(path: str | None = None) -> ScoreConfig:
    source = Path(path) if path else Path(__file__).with_name("health_score.yaml")
    return ScoreConfig.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


def _legacy_config_payload(config: ScoreConfig) -> dict:
    """Keep the v1 digest compatible with rows written before v1.1 fields existed."""
    payload = config.model_dump()
    for category in payload["categories"].values():
        for policy in category["metrics"].values():
            policy.pop("cause_group")
            policy.pop("linear_start")
            if policy["minimum"] == 0:
                policy["minimum"] = 0  # Historical v1 default was serialized as an integer.
    return {key: payload[key] for key in ("categories", "minimum_available_weight", "score_version", "severity", "tcp_min_packets", "weights")}


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def config_hash(config: ScoreConfig) -> str:
    payload = _legacy_config_payload(config) if config.score_version == "health-score-v1" else config.model_dump()
    if config.score_version != "health-score-v1":
        payload = _canonical(payload)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def score_severity(score: float | None, config: ScoreConfig) -> str:
    if score is None:
        return "unknown"
    return "normal" if score >= config.severity.normal_min else "warning" if score >= config.severity.warning_min else "critical"


def metric_value(metrics: dict, path: str):
    section, field = path.split(".")
    return (metrics.get(section) or {}).get(field)


def valid_number(value, policy: MetricPolicy | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return False
    return not policy or (value >= policy.minimum and (policy.maximum is None or value <= policy.maximum)
                          and (not policy.integer or float(value).is_integer()))


def _step_points(value: float, policy: MetricPolicy):
    return next((band for band in reversed(policy.bands)
                 if value > band.threshold or (policy.operator == "ge" and value == band.threshold)), None)


def _linear_points(value: float, policy: MetricPolicy):
    bands = policy.bands
    if value <= policy.linear_start:
        return None
    if value >= bands[-1].threshold:
        return bands[-1], bands[-1].threshold, bands[-1].threshold, float(bands[-1].points)
    previous_threshold, previous_points = policy.linear_start, 0.0
    for band in bands:
        if value <= band.threshold:
            span = band.threshold - previous_threshold
            fraction = 0 if span <= 0 else (value - previous_threshold) / span
            points = previous_points + fraction * (band.points - previous_points)
            return band, previous_threshold, band.threshold, points
        previous_threshold, previous_points = band.threshold, float(band.points)
    return None


def _status_rank(status: str) -> int:
    return {"unknown": 0, "normal": 1, "warning": 2, "critical": 3}[status]


def _at_least(current: str, requested: str) -> str:
    return requested if _status_rank(requested) > _status_rank(current) else current


def _guard_status(base: str, categories: dict, config: ScoreConfig, rule_diagnosis: dict | None):
    guard = config.severity_guard
    if not guard:
        return base, [], None
    status, triggered, reasons = base, [], []
    scores = {name: category.score for name, category in categories.items() if category.available and category.score is not None}
    critical = [name for name, score in scores.items() if score < guard.critical_category_threshold]
    warning = [name for name, score in scores.items() if score < guard.warning_category_threshold]
    if critical:
        status = _at_least(status, guard.critical_category_forces_at_least)
        triggered.append("critical_category")
        reasons.append(f"{', '.join(critical)} 영역 점수가 {guard.critical_category_threshold:g} 미만입니다.")
    elif warning:
        status = _at_least(status, guard.warning_category_forces_at_least)
        triggered.append("warning_category")
        reasons.append(f"{', '.join(warning)} 영역 점수가 {guard.warning_category_threshold:g} 미만입니다.")
    rule_status = (rule_diagnosis or {}).get("severity")
    if rule_status == "critical":
        status = _at_least(status, guard.rule_critical_forces)
        triggered.append("rule_critical")
        reasons.append("Rule Engine이 critical을 보고했습니다.")
    elif rule_status == "warning":
        status = _at_least(status, guard.rule_warning_forces_at_least)
        triggered.append("rule_warning")
        reasons.append("Rule Engine이 warning을 보고했습니다.")
    return status, triggered, " ".join(reasons) if reasons else None


def calculate_score(measurement: dict, config: ScoreConfig, measurement_id: int | None = None,
                    rule_diagnosis: dict | None = None) -> HealthScoreOut:
    metrics = measurement.get("metrics") or {}
    categories = {}
    for name, category in config.categories.items():
        evidence, missing, groups, notes = {}, [], {}, []
        for path, policy in category.metrics.items():
            value = metric_value(metrics, path)
            if not valid_number(value, policy):
                missing.append(path)
                continue
            evidence[path] = value
            if policy.linear_start is not None:
                selection = _linear_points(value, policy)
                band, range_start, range_end, points = selection or (None, None, None, 0)
            else:
                band = _step_points(value, policy)
                range_start, range_end, points = (band.threshold, band.threshold, band.points) if band else (None, None, 0)
            if not band or points <= 0:
                continue
            if name == "tcp" and policy.code == "TCP_RST_OBSERVED" and config.rst_support_thresholds:
                support = any(valid_number(metric_value(metrics, support_path)) and metric_value(metrics, support_path) >= threshold
                              for support_path, threshold in config.rst_support_thresholds.items())
                if not support:
                    notes.append("RST 단독 관측은 전송 장애 근거로 감점하지 않습니다.")
                    continue
            group = policy.group or path
            symbol = ">" if policy.operator == "gt" else "≥"
            deduction = ScoreDeduction(code=policy.code, metric=path, value=value, unit=policy.unit,
                                      threshold=range_end, operator=policy.operator, group=group,
                                      points=round(points, 4), assessed_points=round(points, 4), cause_group=policy.cause_group,
                                      range_start=range_start, range_end=range_end,
                                      calculation="linear" if policy.linear_start is not None else "step",
                                      reason=(f"{path} 실측 {value:g} {policy.unit}: "
                                              f"설정 기준 {symbol} {range_end:g} {policy.unit}"
                                              if policy.linear_start is None else
                                              f"{path} 실측 {value:g} {policy.unit}: "
                                              f"{range_start:g}~{range_end:g} 구간 선형 감점"))
            if group not in groups or groups[group].points < deduction.points:
                groups[group] = deduction
        for collector in measurement.get("collector_status") or []:
            if collector.get("name") in category.collectors and collector.get("status") != "ok":
                notes.append(f"{collector['name']} 수집 상태: {collector.get('status')} (성능 감점과 구분)")
        if missing:
            notes.append("결측·유효하지 않은 지표는 점수 입력에서 제외합니다.")
        low_sample = False
        sample_size = None
        if name == "tcp":
            count = metric_value(metrics, "tcp.captured_packets")
            sample_size = int(count) if valid_number(count) and float(count).is_integer() else None
            low_sample = sample_size is None or count < config.tcp_min_packets
            if valid_number(count):
                evidence["tcp.captured_packets"] = count
            if low_sample:
                notes.append(f"TCP 유효 표본이 {config.tcp_min_packets}개 미만이거나 확인되지 않아 해석 신뢰도가 낮습니다.")
            if config.rst_support_thresholds and valid_number(metric_value(metrics, "tcp.rst")) and metric_value(metrics, "tcp.rst") > 0:
                notes.append("RST는 반복 관측과 추가 전송 이상이 함께 있을 때만 감점합니다. 원인 확정 근거는 아닙니다.")
            if count == 0:
                # No packets cannot support a measured zero retransmission rate.
                groups, evidence = {}, {"tcp.captured_packets": 0}
                missing = list(category.metrics)
        available = len(missing) < len(category.metrics)
        deductions = sorted(groups.values(), key=lambda d: (-d.points, d.metric))
        applied, remaining = [], 100
        for deduction in deductions:
            deduction = deduction.model_copy(update={"points": min(deduction.points, remaining)})
            remaining = round(remaining - deduction.points, 4)
            if deduction.points:
                applied.append(deduction)
        score = remaining if available else None
        coverage = round((len(category.metrics) - len(missing)) / len(category.metrics), 4)
        categories[name] = CategoryScore(score=score, severity=score_severity(score, config), available=available,
                                        coverage=coverage,
                                        quality="unavailable" if not available else "low_sample" if low_sample and config.score_version != "health-score-v1" else "partial" if notes else "complete",
                                        low_sample=low_sample, sample_size=sample_size, evidence=evidence,
                                        missing_metrics=missing, notes=notes, deductions=applied)
    included = sum(config.weights[name] for name, category in categories.items() if category.available)
    coverage = sum(config.weights[name] * category.coverage for name, category in categories.items())
    available = included >= config.minimum_available_weight
    score = round(sum(category.score * config.weights[name] for name, category in categories.items() if category.available) / included, 2) if available else None
    partial = any(category.quality != "complete" for category in categories.values())
    low_confidence = config.score_version != "health-score-v1" and any(category.low_sample for category in categories.values())
    notes = ["측정 범위/표본 제한이 있습니다. 점수는 수집된 지표에 대한 평가입니다."] if partial else []
    if included < 1:
        notes.append("계산 불가 영역의 가중치를 제외하고 나머지를 정규화했습니다.")
    if low_confidence:
        notes.append("작은 표본 Category가 있어 Overall 해석 신뢰도가 낮습니다.")
    if config.severity_guard and rule_diagnosis is None:
        notes.append("Rule 결과가 제공되지 않아 Category Guard만 평가했습니다.")
    if not available:
        notes.append("유효 영역 가중치가 최소 기준에 미달해 전체 점수를 제공하지 않습니다.")
    causes = [ScoreCause(**deduction.model_dump(), category=name,
                         weighted_points=round(deduction.points * config.weights[name] / included, 4))
              for name, category in categories.items() for deduction in category.deductions] if included else []
    base_status = score_severity(score, config)
    final_status, guard_triggered, guard_reason = _guard_status(base_status, categories, config, rule_diagnosis)
    return HealthScoreOut(measurement_id=measurement_id, score_version=config.score_version, config_hash=config_hash(config),
                          weights=config.weights, categories=categories,
                          overall=OverallScore(score=score, severity=final_status, base_severity=base_status,
                                               status=final_status, guard_triggered=guard_triggered, guard_reason=guard_reason,
                                               available=available,
                                               coverage=round(coverage, 4), included_weight=round(included, 4),
                                               quality="unavailable" if not available else "low_confidence" if low_confidence else "partial" if partial else "complete", notes=notes),
                          top_causes=sorted(causes, key=lambda cause: (-cause.weighted_points, cause.category, cause.metric)))
