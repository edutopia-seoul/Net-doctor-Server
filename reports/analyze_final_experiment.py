"""Read-only audit of PostgreSQL measurements 21–40; write presentation CSVs."""

import csv
import json
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.rule_engine import diagnose


OUT = Path(__file__).resolve().parent
AGENT_ID = "549dc09b-4438-4e02-ad3b-2e70c4110b95"
CONDITIONS = ("NORMAL", "HIGH_LATENCY", "PACKET_LOSS", "MIXED")
LABELS = ("NORMAL", "LATENCY", "LOSS", "MIXED")
METRICS = {
    "gateway_rtt_ms": ("gateway_ping", "avg_rtt_ms"),
    "gateway_loss_pct": ("gateway_ping", "packet_loss_pct"),
    "internet_rtt_ms": ("internet_ping", "avg_rtt_ms"),
    "internet_loss_pct": ("internet_ping", "packet_loss_pct"),
    "dns_system_ms": ("dns", "system_ms"),
    "dns_google_ms": ("dns", "google_ms"),
    "dns_cloudflare_ms": ("dns", "cloudflare_ms"),
    "traceroute_hop_count": ("traceroute", "hop_count"),
    "http_dns_ms": ("http", "dns_ms"),
    "http_connect_ms": ("http", "connect_ms"),
    "http_tls_ms": ("http", "tls_ms"),
    "http_ttfb_ms": ("http", "ttfb_ms"),
    "http_total_ms": ("http", "total_ms"),
    "tcp_captured_packets": ("tcp", "captured_packets"),
    "tcp_retransmissions": ("tcp", "retransmissions"),
    "tcp_retransmission_pct": ("tcp", "retransmission_pct"),
    "tcp_duplicate_ack": ("tcp", "duplicate_ack"),
    "tcp_rst": ("tcp", "rst"),
    "tcp_zero_window": ("tcp", "zero_window"),
}
SQL = """
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
FROM (
  SELECT m.id, m.agent_id, m.timestamp, m.created_at, m.target_profile,
         m.network, m.metrics, m.collector_status,
         r.id AS rule_id, r.severity AS rule_severity,
         r.findings AS rule_findings, r.triggered_rules,
         a.id AS ai_id, a.available AS ai_available, a.severity AS ai_severity,
         a.primary_cause, a.confidence, a.measured_facts,
         a.rule_findings AS ai_rule_findings, a.hypotheses, a.impact,
         a.recommendations, a.additional_checks, a.model, a.error
  FROM measurements m
  LEFT JOIN rule_diagnoses r ON r.measurement_id = m.id
  LEFT JOIN ai_diagnoses a ON a.measurement_id = m.id
  WHERE m.id BETWEEN 21 AND 40
  ORDER BY m.id
) t;
"""


def write_csv(name, headers, rows):
    with (OUT / name).open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["null" if value is None else
                             json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                             for value in row])


def main():
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "netdoctor",
         "-d", "netdoctor", "-At", "-c", SQL], cwd=ROOT, text=True,
        capture_output=True, check=True,
    )
    rows = json.loads(result.stdout)
    assert [row["id"] for row in rows] == list(range(21, 41)), "ID 21–40 must each exist once"
    assert all(row["agent_id"] == AGENT_ID for row in rows), "unexpected agent"
    assert len({row["timestamp"] for row in rows}) == 20, "duplicate timestamp"
    assert len({json.dumps([row[key] for key in ("timestamp", "network", "metrics", "collector_status")], sort_keys=True)
                for row in rows}) == 20, "duplicate measurement payload"
    assert all(row["timestamp"] and row["metrics"] and row["network"] and row["collector_status"]
               and row["rule_id"] and row["ai_id"] for row in rows), "incomplete DB row"

    detailed = []
    for row in rows:
        condition = CONDITIONS[(row["id"] - 21) // 5]
        number = (row["id"] - 21) % 5 + 1
        label = f"{LABELS[(row['id'] - 21) // 5]}-{number:02d}"
        values = {name: (row["metrics"].get(section) or {}).get(field)
                  for name, (section, field) in METRICS.items()}
        recalculated = diagnose(row["metrics"], str(ROOT / "backend/app/rules.yaml"))
        rule_exact = (recalculated["severity"] == row["rule_severity"]
                      and recalculated["triggered_rules"] == row["triggered_rules"]
                      and recalculated["findings"] == row["rule_findings"])
        expected_facts = [f"{section}.{key}={value}" for section, fields in row["metrics"].items()
                          if isinstance(fields, dict) for key, value in fields.items()
                          if isinstance(value, (int, float, str)) and not isinstance(value, bool)]
        facts_exact = Counter(expected_facts) == Counter(row["measured_facts"] or [])
        ai_rules_exact = row["ai_rule_findings"] == row["rule_findings"]
        detailed.append((row, condition, label, values, rule_exact, facts_exact, ai_rules_exact))

    headers = ["label", "condition", "measurement_id", "agent_id", "timestamp", "created_at",
               "default_interface", "local_ip", "gateway", "dns_servers", *METRICS,
               "collector_status", "rule_severity", "triggered_rules", "rule_findings",
               "rule_evidence_consistent", "ai_available", "ai_severity", "ai_primary_cause",
               "ai_confidence", "ai_measured_facts", "ai_rule_findings", "ai_hypotheses",
               "ai_impact", "ai_recommendations", "ai_additional_checks", "ai_model",
               "measured_facts_exact", "ai_rule_findings_exact"]
    write_csv("final_experiment_measurements.csv", headers, [
        [label, condition, row["id"], row["agent_id"], row["timestamp"], row["created_at"],
         row["network"].get("default_interface"), row["network"].get("local_ip"),
         row["network"].get("gateway"), row["network"].get("dns_servers"),
         *values.values(), row["collector_status"], row["rule_severity"], row["triggered_rules"],
         row["rule_findings"], "YES" if rule_exact else "NO", row["ai_available"],
         row["ai_severity"], row["primary_cause"], row["confidence"], row["measured_facts"],
         row["ai_rule_findings"], row["hypotheses"], row["impact"], row["recommendations"],
         row["additional_checks"], row["model"], facts_exact, ai_rules_exact]
        for row, condition, label, values, rule_exact, facts_exact, ai_rules_exact in detailed
    ])

    stat_rows = []
    summary_rows = []
    for condition in CONDITIONS:
        subset = [item for item in detailed if item[1] == condition]
        stats = {}
        for name in METRICS:
            valid = [item[3][name] for item in subset if item[3][name] is not None]
            stats[name] = (len(valid), statistics.mean(valid) if valid else None,
                           statistics.stdev(valid) if len(valid) > 1 else None,
                           min(valid) if valid else None, max(valid) if valid else None)
            stat_rows.append((condition, name, *stats[name]))
        severities = Counter(item[0]["rule_severity"] for item in subset)
        summary_rows.append((condition, len(subset),
                             *[stats[name][1] for name in ("gateway_rtt_ms", "internet_rtt_ms",
                                                            "internet_loss_pct", "dns_system_ms",
                                                            "http_ttfb_ms", "tcp_retransmission_pct")],
                             stats["dns_system_ms"][0], *[severities[level] for level in
                                                           ("normal", "warning", "critical")],
                             sum(item[0]["ai_available"] is True for item in subset)))

    write_csv("final_experiment_stats.csv", ["condition", "metric", "valid_n", "mean", "sample_sd", "min", "max"], stat_rows)
    write_csv("final_experiment_summary.csv", ["condition", "measurement_n", "avg_gateway_rtt_ms",
          "avg_internet_rtt_ms", "avg_internet_loss_pct", "avg_dns_system_ms", "avg_http_ttfb_ms",
          "avg_tcp_retransmission_pct", "dns_system_valid_n", "rule_normal_n", "rule_warning_n",
          "rule_critical_n", "ai_available_n"], summary_rows)
    print(f"rows={len(rows)} rules_recomputed={sum(item[4] for item in detailed)}/20 "
          f"ai_available={sum(item[0]['ai_available'] is True for item in detailed)}/20 "
          f"facts_exact={sum(item[5] for item in detailed)}/20 "
          f"ai_rule_findings_exact={sum(item[6] for item in detailed)}/20")
    for summary in summary_rows:
        print(summary)


if __name__ == "__main__":
    main()
