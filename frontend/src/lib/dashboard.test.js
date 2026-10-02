import assert from 'node:assert/strict';
import test from 'node:test';
import { chartPoints, metricStatus, previousChange } from './dashboard.js';

test('missing DNS stays missing; real zero loss remains a plotted value', () => {
  const rows = [
    { id: 1, timestamp: '2026-09-28T10:00:00Z', metrics: { dns: { system_ms: null }, internet_ping: { packet_loss_pct: 0 } } },
    { id: 2, timestamp: '2026-09-28T10:01:00Z', metrics: { dns: { system_ms: 25 }, internet_ping: { packet_loss_pct: 10 } } },
  ];
  assert.deepEqual(chartPoints(rows, 'dns.system_ms').map(point => point.id), [2]);
  assert.deepEqual(chartPoints(rows, 'internet_ping.packet_loss_pct').map(point => point.value), [0, 10]);
  assert.equal(previousChange(rows, 'dns.system_ms'), null);
  assert.equal(previousChange(rows, 'internet_ping.packet_loss_pct'), 10);
  assert.equal(metricStatus({ triggered_rules: ['EXTERNAL_PACKET_LOSS'] }, 10, ['EXTERNAL_PACKET_LOSS']), 'warning');
  assert.equal(metricStatus({ triggered_rules: ['INTERNET_UNREACHABLE'] }, null, ['INTERNET_UNREACHABLE']), 'critical');
});

test('score history plots only stored scores, including real zero', () => {
  const rows = [
    { id: 21, timestamp: '2026-09-28T10:00:00Z', health_score: { overall: { score: 100 } } },
    { id: 22, timestamp: '2026-09-28T10:01:00Z', health_score: null },
    { id: 23, timestamp: '2026-09-28T10:02:00Z', health_score: { overall: { score: 0 } } },
  ];
  assert.deepEqual(chartPoints(rows, 'health_score.overall.score').map(point => point.value), [100, 0]);
});
