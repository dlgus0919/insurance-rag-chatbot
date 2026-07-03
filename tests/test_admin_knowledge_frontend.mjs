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

test('admin config defines knowledge intake audit endpoint base', async () => {
  const { API_CONFIG } = await import('../frontend/js/config.js');

  assert.equal(
    API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE,
    '/admin/knowledge/intake/jobs'
  );
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
  assert.equal(formatBlockReason('source_file_missing'), '업로드 원본 파일을 찾을 수 없습니다.');
  assert.equal(formatBlockReason('excel_staging_not_ready'), 'Excel 문서 구조화 staging이 아직 연결되지 않았습니다.');
});

test('admin module exports candidate review helpers', async () => {
  const module = await import('../frontend/js/modules/admin.js');
  assert.equal(typeof module.fetchOntologyCandidates, 'function');
  assert.equal(typeof module.decideOntologyCandidate, 'function');
  assert.equal(typeof module.fetchRuleCandidates, 'function');
  assert.equal(typeof module.decideRuleCandidate, 'function');
});

test('ontology candidate cards expose practitioner review context', async () => {
  const { renderCandidateList } = await import('../frontend/js/pages/admin.js');

  const html = renderCandidateList([
    {
      candidate_id: 'dev.cov.rider.123',
      status: 'pending',
      canonical_name: '특약',
      concept_id: 'cov.rider',
      candidate_aliases: ['운전자한정특약', '<script>alert("x")</script>'],
      properties: {
        display: {
          summary: '특약 표현을 같은 보험 업무 개념으로 묶어 검색 보강에 사용합니다.',
          example_questions: ['특약에 해당하면 보험금을 받을 수 있나요?'],
          approval_prompt: '위 표현들을 같은 보험 업무 개념으로 묶어도 될까요?',
        },
      },
      source_evidence: [
        {
          doc_short: '상담사례집',
          page: '3',
          excerpt: '운전자한정특약에 가입되어 있다면 보상 여부를 확인합니다.',
        },
      ],
    },
  ], 'ontology');

  assert.match(html, /승인 대상 표현/);
  assert.match(html, /운전자한정특약/);
  assert.match(html, /특약 표현을 같은 보험 업무 개념으로 묶어 검색 보강에 사용합니다\./);
  assert.match(html, /특약에 해당하면 보험금을 받을 수 있나요\?/);
  assert.match(html, /위 표현들을 같은 보험 업무 개념으로 묶어도 될까요\?/);
  assert.match(html, /상담사례집 · 3쪽/);
  assert.match(html, /운전자한정특약에 가입되어 있다면 보상 여부를 확인합니다\./);
  assert.match(html, /&lt;script&gt;alert\(&quot;x&quot;\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>alert/);
});

test('knowledge section has apply approved button', async () => {
  const html = await readFile(new URL('../frontend/html/admin.html', import.meta.url), 'utf8');
  assert.match(html, /data-admin-action="apply-approved-knowledge"/);
});

test('admin apply approved copy mentions search index promotion', async () => {
  const js = await readFile(new URL('../frontend/js/pages/admin.js', import.meta.url), 'utf8');

  assert.match(js, /문서 원문 검색 인덱스\(BM25\/Chroma\)/);
  assert.match(js, /문서 원문 검색 인덱스를 active DB에 반영/);
  assert.match(js, /status !== 'completed'/);
  assert.match(js, /index_rebuilt/);
  assert.match(js, /graph_rebuilt/);
});
