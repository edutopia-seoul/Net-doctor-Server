from pathlib import Path

import yaml


def diagnose(metrics: dict, config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        path = Path(__file__).with_name("rules.yaml")
    config = yaml.safe_load(path.read_text())
    findings: list[str] = []
    triggered: list[str] = []
    severity = "normal"

    def val(section: str, key: str):
        return (metrics.get(section) or {}).get(key)

    def add(rule: str, message: str, level: str = "warning"):
        nonlocal severity
        triggered.append(rule)
        findings.append(message)
        if level == "critical" or (level == "warning" and severity == "normal"):
            severity = level

    gateway_loss, gateway_rtt = val("gateway_ping", "packet_loss_pct"), val("gateway_ping", "avg_rtt_ms")
    internet_loss, internet_rtt = val("internet_ping", "packet_loss_pct"), val("internet_ping", "avg_rtt_ms")
    if gateway_loss is not None and gateway_loss >= 100:
        add("GATEWAY_UNREACHABLE", f"gateway packet loss is {gateway_loss}%", "critical")
    elif gateway_loss is not None and gateway_loss >= config["gateway"]["high_loss_pct"]:
        add("LOCAL_PACKET_LOSS", f"gateway packet loss is {gateway_loss}%")
    if internet_loss is not None and internet_loss >= 100:
        add("INTERNET_UNREACHABLE", f"internet packet loss is {internet_loss}%", "critical")
    elif internet_loss is not None and internet_loss >= config["internet"]["high_loss_pct"]:
        add("EXTERNAL_PACKET_LOSS", f"internet packet loss is {internet_loss}%")
    if internet_rtt is not None and internet_rtt > config["internet"]["high_rtt_ms"]:
        add("EXTERNAL_HIGH_LATENCY", f"internet average RTT is {internet_rtt} ms")
    if gateway_rtt is not None and gateway_rtt > config["gateway"]["high_rtt_ms"]:
        add("LOCAL_HIGH_LATENCY", f"gateway average RTT is {gateway_rtt} ms")
    for name in ("system_ms", "cloudflare_ms", "google_ms"):
        value = val("dns", name)
        if value is not None and value > config["dns"]["slow_ms"]:
            add("DNS_DELAY", f"DNS {name} response is {value} ms")
    retransmission = val("tcp", "retransmission_pct")
    if retransmission is not None and retransmission >= config["tcp"]["retransmission_warning_pct"]:
        add("TCP_RETRANSMISSION_HIGH", f"TCP retransmission rate is {retransmission}%")
    ttfb = val("http", "ttfb_ms")
    if ttfb is not None and ttfb > config["http"]["high_ttfb_ms"]:
        add("HTTP_SERVER_RESPONSE_DELAY", f"HTTP TTFB is {ttfb} ms")
    if not triggered and not any(value is not None for name in ("gateway_ping", "internet_ping", "dns", "http", "tcp")
                                 for value in (metrics.get(name) or {}).values()):
        add("INSUFFICIENT_DATA", "no usable network metrics were supplied")
    return {"severity": severity, "findings": findings, "triggered_rules": triggered}
