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
