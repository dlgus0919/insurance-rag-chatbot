import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('admin page exposes knowledge extension section', async () => {
  const html = await readFile(new URL('../frontend/html/admin.html', import.meta.url), 'utf8');
  assert.match(html, /data-admin-sub="knowledge"/);
  assert.match(html, /문서 추가/);
  assert.match(html, /후보 검토/);
  assert.match(html, /id="knowledge-active-rule-list"/);
  assert.match(html, /id="knowledge-active-rule-count">확인 중/);
  assert.doesNotMatch(html, /knowledge-active-rule-count">0건/);
});

test('admin module exports knowledge intake API helpers', async () => {
  const module = await import('../frontend/js/modules/admin.js');
  assert.equal(typeof module.fetchKnowledgeIntakeJobs, 'function');
  assert.equal(typeof module.createKnowledgeIntakeJob, 'function');
  assert.equal(typeof module.runKnowledgeIntakeJob, 'function');
});

test('rag graph sync uses active or corrected OCR index', async () => {
  const pageJs = await readFile(new URL('../frontend/js/pages/admin.js', import.meta.url), 'utf8');
  const moduleJs = await readFile(new URL('../frontend/js/modules/admin.js', import.meta.url), 'utf8');

  assert.match(pageJs, /effective_index_mode \|\| data\?\.index_mode \|\| 'v2_only'/);
  assert.doesNotMatch(pageJs, /indexMode: 'default'/);
  assert.match(moduleJs, /options\.indexMode \|\| options\.index_mode \|\| 'v2_only'/);
});

test('admin page exposes intake audit panel', async () => {
  const html = await readFile(new URL('../frontend/html/admin.html', import.meta.url), 'utf8');

  assert.match(html, /id="knowledge-audit-detail"/);
  assert.match(html, /data-admin-action="load-knowledge-audit"/);
});

test('admin module exports intake audit helper', async () => {
  const module = await import('../frontend/js/modules/admin.js');

  assert.equal(typeof module.fetchKnowledgeIntakeAudit, 'function');
  assert.equal(typeof module.fetchActiveRules, 'function');
});

test('admin config defines knowledge intake audit endpoint base', async () => {
  const { API_CONFIG } = await import('../frontend/js/config.js');

  assert.equal(
    API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE,
    '/admin/knowledge/intake/jobs'
  );
  assert.equal(API_CONFIG.ENDPOINTS.ADMIN_ACTIVE_RULES, '/admin/knowledge/active-rules');
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



test('active rule list renders practitioner-readable current values', async () => {
  const { renderActiveRuleList } = await import('../frontend/js/pages/admin.js');

  const html = renderActiveRuleList([
    {
      section: 'rules',
      rule_id: 'deductible.4th.benefit.outpatient',
      copay_ratio: '0.2',
      min_deductible: '10000',
      annual_visit_limit: 180,
      description: '4세대 급여 통원',
      source_doc: '약관',
      source_page: '31',
      source_clause: '제3조',
    },
  ]);

  assert.match(html, /4세대 급여 통원/);
  assert.match(html, /본인부담금\/지급 비율: 20%/);
  assert.match(html, /최소 공제금: 10,000원/);
  assert.match(html, /연간 횟수 한도: 180회/);
  assert.match(html, /약관 · 31 · 제3조/);
});

test('rule candidate cards use practitioner labels and review context', async () => {
  const { renderCandidateList } = await import('../frontend/js/pages/admin.js');

  const html = renderCandidateList([
    {
      candidate_id: 'rulecand.test',
      status: 'pending',
      proposed_rule: {
        rule_id: 'deductible.1th.unknown.hospitalization.test',
        generation: '1th',
        category: 'unknown',
        visit_type: 'hospitalization',
        facility_grade: 'all',
        copay_ratio: '0.2',
        min_deductible: '0',
        description: '1th unknown hospitalization: 본인부담금 20%',
        source_clause: '1세대 입원 보상 근거',
      },
      evidence_text: '1세대 입원 보상 근거',
    },
  ], 'rule');

  assert.match(html, /1세대/);
  assert.match(html, /입원/);
  assert.match(html, /급여\/비급여 미확정/);
  assert.match(html, /전체 의료기관/);
  assert.match(html, /확인할 계산 조건/);
  assert.match(html, /원문 근거/);
  assert.doesNotMatch(html, /1th unknown hospitalization/);
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

test('ontology candidate cards expose explicit field approval choices', async () => {
  const { renderCandidateList } = await import('../frontend/js/pages/admin.js');

  const html = renderCandidateList([
    {
      candidate_id: 'cand-approval-path',
      status: 'pending',
      canonical_name: '검토 후보',
      approval_operations: [
        {
          path: '/concepts/cond.alpha/evidence_tags/hash-alpha',
          field_label: '근거 태그',
          value_preview: 'source:alpha',
          value_hash: 'hash-alpha',
        },
      ],
      runtime_properties: { internal_value: 'must-not-render' },
    },
  ], 'ontology');

  assert.match(html, /승인할 변경 항목/);
  assert.match(html, /data-ontology-approval-path/);
  assert.match(html, /근거 태그/);
  assert.match(html, /source:alpha/);
  assert.doesNotMatch(html, /must-not-render/);
});
