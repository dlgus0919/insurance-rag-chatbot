import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('admin page exposes knowledge extension section', async () => {
  const html = await readFile(new URL('../frontend/html/admin.html', import.meta.url), 'utf8');
  assert.match(html, /data-admin-sub="knowledge"/);
  assert.match(html, /문서 추가/);
  assert.match(html, /후보 검토/);
});

test('admin module exports knowledge intake API helpers', async () => {
  const module = await import('../frontend/js/modules/admin.js');
  assert.equal(typeof module.fetchKnowledgeIntakeJobs, 'function');
  assert.equal(typeof module.createKnowledgeIntakeJob, 'function');
  assert.equal(typeof module.runKnowledgeIntakeJob, 'function');
});

test('admin page exposes intake audit panel', async () => {
  const html = await readFile(new URL('../frontend/html/admin.html', import.meta.url), 'utf8');

  assert.match(html, /id="knowledge-audit-detail"/);
  assert.match(html, /data-admin-action="load-knowledge-audit"/);
});

test('admin module exports intake audit helper', async () => {
  const module = await import('../frontend/js/modules/admin.js');

  assert.equal(typeof module.fetchKnowledgeIntakeAudit, 'function');
});

test('audit detail renders failed event fallback reason and next action', async () => {
  const { renderAuditDetail } = await import('../frontend/js/pages/admin.js');

  const html = renderAuditDetail([
    {
      event_type: 'failed',
      message: '후보 생성 실패',
      to_status: 'failed',
    },
  ]);

  assert.match(html, /후보 생성 실패/);
  assert.match(html, /감사 이력과 서버 로그를 확인한 뒤 문서 처리를 다시 실행하세요\./);
});

test('audit detail escapes failed event message HTML', async () => {
  const { renderAuditDetail, formatBlockReason } = await import('../frontend/js/pages/admin.js');

  const html = renderAuditDetail([
    {
      event_type: 'failed',
      message: '<script>alert("x")</script>',
      to_status: 'failed',
    },
  ]);

  assert.match(html, /&lt;script&gt;alert\(&quot;x&quot;\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>alert/);
  assert.equal(formatBlockReason('x'), '알 수 없는 차단 사유: x');
});

test('admin module exports candidate review helpers', async () => {
  const module = await import('../frontend/js/modules/admin.js');
  assert.equal(typeof module.fetchOntologyCandidates, 'function');
  assert.equal(typeof module.decideOntologyCandidate, 'function');
  assert.equal(typeof module.fetchRuleCandidates, 'function');
  assert.equal(typeof module.decideRuleCandidate, 'function');
});

test('knowledge section has apply approved button', async () => {
  const html = await readFile(new URL('../frontend/html/admin.html', import.meta.url), 'utf8');
  assert.match(html, /data-admin-action="apply-approved-knowledge"/);
});
