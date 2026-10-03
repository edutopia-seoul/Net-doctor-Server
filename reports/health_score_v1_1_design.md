# health-score-v1.1 — implementation policy fixed before experiment backfill

2026-10-04 KST. v2.0-health-score-v1 tag: 2452a0e; feature/health-score-v1-1.

- Preserve Measurement/Rule/AI/v1 rows, v1 YAML and v1 step deductions/hash.
- Weights .20/.25/.15/.20/.20 unchanged. Score is still a weighted mean.
- Final status is max(base score severity, stored Rule severity floor, Category floor).
  Category <40 and <60 each force at least warning; Rule critical forces critical.
  Guard never reduces a score. Missing Rule is explicitly recorded, never inferred normal.
- Linear interpolation for six metrics ONLY: Gateway RTT onset10ms, Internet RTT
  onset75ms, both loss onset0%, TCP retransmission onset0.5%, TTFB onset400ms.
  Non-loss onset is half the first v1 boundary. The existing positive v1 boundary/point
  pairs become interpolation anchors; endpoints saturate at final configured deduction.
  This general rule was chosen before observing v1.1 experiment scores, not fitted to IDs.
  Remaining metrics stay stepwise. Within-category max groups and the 100-point cap stay.
- Cause groups LATENCY/LATENCY_EFFECT and PACKET_LOSS/TCP_DEGRADATION describe possibly
  related effects, not proven shared causes; cross-category deductions remain unchanged.
- TCP weight stays .20; sample_size and low_sample quality explicit (<50 packets).
  Overall low_confidence if any low_sample, otherwise partial for missing coverage,
  complete otherwise; unavailable when insufficient available category weight.
- RST1 has no penalty even with another fault. RST>=5 is penalized only with retrans>=5%,
  duplicate ACK>=3, or zero window>=1; retained repeated-RST anchor is 25 points.
- Coverage policy unchanged. ID33 system DNS and ID34 Google DNS are both missing:
  correct baseline coverage counts are eighteen .95 and two .90.
- Canonical sorted numeric JSON for new version hash only. v1 legacy serialization retained.
- Default server policy becomes v1.1; historical v1 selected explicitly via score_version query.
  Backfill uses stored Rule results; no old diagnosis recalculation/writes or AI calls.
- Verify v1 full-row hashes, v1 recalculation on all20, dry-run/apply/repeat, both version APIs,
  all existing tests plus boundary/guard/low sample/RST/canonical hash, build and real browser.
