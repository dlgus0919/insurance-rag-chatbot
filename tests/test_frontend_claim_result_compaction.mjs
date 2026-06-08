import test from 'node:test';
import assert from 'node:assert/strict';

import { compactClaimBasisItems } from '../frontend/js/modules/claim-result.js';

test('compacts duplicate claim basis entries by source', () => {
  const compacted = compactClaimBasisItems([
    { source: '약관', content: '첫 번째 근거' },
    { source: '약관', content: '두 번째 근거' },
    { source: '표준약관', content: '표준 근거' },
    { source: '상담사례집', content: '' },
  ]);

  assert.deepEqual(compacted, [
    { source: '약관', content: '첫 번째 근거', extraCount: 1 },
    { source: '표준약관', content: '표준 근거', extraCount: 0 },
  ]);
});

test('limits compacted claim basis items', () => {
  const compacted = compactClaimBasisItems([
    { source: 'A', content: 'a' },
    { source: 'B', content: 'b' },
    { source: 'C', content: 'c' },
  ], 2);

  assert.equal(compacted.length, 2);
  assert.equal(compacted[0].source, 'A');
  assert.equal(compacted[1].source, 'B');
});
