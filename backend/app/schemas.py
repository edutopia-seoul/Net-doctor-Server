from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class InterfaceInfo(BaseModel):
    name: str
    mac: str | None = None
    ipv4: list[str] = Field(default_factory=list)
    link_speed_mbps: int | None = None


class AgentRegister(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    hostname: str
    os: str
    agent_version: str
    interfaces: list[InterfaceInfo] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class TargetProfile(BaseModel):
    internet_host: str | None = None
    dns_domain: str | None = None
    http_url: str | None = None
    iperf_host: str | None = None


class PingMetrics(BaseModel):
    min_rtt_ms: float | None = None
    avg_rtt_ms: float | None = None
    max_rtt_ms: float | None = None
    packet_loss_pct: float | None = None
    jitter_ms: float | None = None


class DNSMetrics(BaseModel):
    system_ms: float | None = None
    cloudflare_ms: float | None = None
    google_ms: float | None = None
    resolved_ip: str | None = None


class TracerouteMetrics(BaseModel):
    hop_count: int | None = None
    latency_jump_hop: int | None = None
    latency_jump_ms: float | None = None
    hops: list[Any] = Field(default_factory=list)


class HTTPMetrics(BaseModel):
    dns_ms: float | None = None
    connect_ms: float | None = None
    tls_ms: float | None = None
    ttfb_ms: float | None = None
    total_ms: float | None = None
    status_code: int | None = None


class TCPMetrics(BaseModel):
    captured_packets: int | None = None
    retransmissions: int | None = None
    retransmission_pct: float | None = None
    duplicate_ack: int | None = None
    rst: int | None = None
    zero_window: int | None = None


class ThroughputMetrics(BaseModel):
    tcp_mbps: float | None = None
    udp_mbps: float | None = None
    udp_jitter_ms: float | None = None
    udp_loss_pct: float | None = None


class Metrics(BaseModel):
    gateway_ping: PingMetrics | None = None
    internet_ping: PingMetrics | None = None
    dns: DNSMetrics | None = None
    traceroute: TracerouteMetrics | None = None
    http: HTTPMetrics | None = None
    tcp: TCPMetrics | None = None
    throughput: ThroughputMetrics | None = None


class NetworkInfo(BaseModel):
    default_interface: str | None = None
    local_ip: str | None = None
    gateway: str | None = None
    dns_servers: list[str] = Field(default_factory=list)


class CollectorStatus(BaseModel):
    name: str
    status: str
    message: str = ""


class MeasurementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(pattern=r"^1\.0$")
    agent_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    target_profile: TargetProfile
    network: NetworkInfo
    metrics: Metrics
    collector_status: list[CollectorStatus] = Field(default_factory=list)


class RuleDiagnosisOut(BaseModel):
    severity: str
    findings: list[str]
    triggered_rules: list[str]


class AIDiagnosisOut(BaseModel):
    available: bool
    severity: str | None = None
    primary_cause: str | None = None
    confidence: str | None = None
    measured_facts: list[str] = Field(default_factory=list)
    rule_findings: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    impact: str | None = None
    recommendations: list[str] = Field(default_factory=list)
    additional_checks: list[str] = Field(default_factory=list)
    model: str | None = None
    error: str | None = None


class AgentOut(BaseModel):
    agent_id: str
    hostname: str
    os: str
    agent_version: str
    last_seen: datetime
    created_at: datetime
    metadata: dict


class ScoreDeduction(BaseModel):
    code: str
    metric: str
    value: float
    unit: str
    threshold: float
    operator: Literal["gt", "ge"]
    points: int = Field(ge=0, le=100)
    assessed_points: int = Field(ge=0, le=100)
    reason: str
    group: str


class CategoryScore(BaseModel):
    score: float | None = Field(default=None, ge=0, le=100)
    severity: Literal["normal", "warning", "critical", "unknown"]
    available: bool
    coverage: float = Field(ge=0, le=1)
    quality: Literal["complete", "partial", "unavailable"]
    low_sample: bool = False
    evidence: dict[str, float] = Field(default_factory=dict)
    missing_metrics: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    deductions: list[ScoreDeduction] = Field(default_factory=list)


class OverallScore(BaseModel):
    score: float | None = Field(default=None, ge=0, le=100)
    severity: Literal["normal", "warning", "critical", "unknown"]
    available: bool
    coverage: float = Field(ge=0, le=1)
    included_weight: float = Field(ge=0, le=1)
    quality: Literal["complete", "partial", "unavailable"]
    notes: list[str] = Field(default_factory=list)


class ScoreCause(ScoreDeduction):
    category: str
    weighted_points: float = Field(ge=0, le=100)


class HealthScoreOut(BaseModel):
    measurement_id: int | None = None
    score_version: str
    config_hash: str
    weights: dict[str, float]
    overall: OverallScore
    categories: dict[str, CategoryScore]
    top_causes: list[ScoreCause] = Field(default_factory=list)
    created_at: datetime | None = None


class MeasurementOut(BaseModel):
    id: int
    agent_id: str
    timestamp: datetime
    target_profile: dict
    network: dict
    metrics: dict
    collector_status: list
    created_at: datetime
    health_score: HealthScoreOut | None = None


class DiagnosisOut(BaseModel):
    measurement: MeasurementOut
    rule_diagnosis: RuleDiagnosisOut
    ai_diagnosis: AIDiagnosisOut
