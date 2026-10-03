import test from 'node:test';
import assert from 'node:assert/strict';
import { groupScoreCauses } from './presentation.js';

test('related effects group for explanation without changing deductions', () => {
  const causes = [{ cause_group: 'LATENCY', weighted_points: 10 },
    { cause_group: 'LATENCY_EFFECT', weighted_points: 5 },
    { cause_group: 'PACKET_LOSS', weighted_points: 11.25 },
    { cause_group: 'TCP_DEGRADATION', weighted_points: 5 }];
  const before = JSON.stringify(causes);
  const groups = groupScoreCauses(causes);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups.map(group => group.points), [15, 16.25]);
  assert.equal(groups.flatMap(group => group.effects).length, 4);
  assert.equal(JSON.stringify(causes), before);
  assert.deepEqual(groupScoreCauses(), []);
});
