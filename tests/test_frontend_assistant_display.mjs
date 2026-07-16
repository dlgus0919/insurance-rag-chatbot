import test from 'node:test';
import assert from 'node:assert/strict';

import {
  hasRenderableGraphPayload,
  renderCanonicalDecisionHtml,
  renderClarificationHtml,
  renderGraphFactsHtml,
  renderGraphReviewPathsHtml,
  sanitizeAssistantAnswer,
} from '../frontend/js/pages/chat.js';

const structuredAnswer = [
  'N39.3은 보상 제외로 판단됩니다.',
  '',
  '■ 섹션 1️⃣ 【확정 근거】',
  '해당 없음',
  '■ 섹션 2️⃣ 【검토 필요 사항】',
  '- 질병/상해 구분 확인',
  '',
  '[출처: 약관, p.12]',
].join('\n');

test('keeps model-written structured template when graph payload is empty', () => {
  const emptyGraph = { graph_review_paths: [], facts: [], plan: {} };

  const sanitized = sanitizeAssistantAnswer(structuredAnswer, emptyGraph);

  assert.equal(hasRenderableGraphPayload(emptyGraph), false);
  assert.match(sanitized, /■ 섹션 1️⃣/);
  assert.match(sanitized, /【확정 근거】/);
  assert.doesNotMatch(sanitized, /\[출처:/);
});

test('strips duplicate model-written template when graph panel can render', () => {
  const graph = {
    graph_review_paths: [
      {
        path_type: 'diagnosis_review',
        path_type_label: '진단코드 검토',
        status: 'confirmed',
        status_label: '확정',
        summary: '문서에 직접 언급된 진단코드 근거 확인',
      },
    ],
  };

  const sanitized = sanitizeAssistantAnswer(structuredAnswer, graph);
  const panelHtml = renderGraphReviewPathsHtml(graph);

  assert.equal(hasRenderableGraphPayload(graph), true);
  assert.equal(sanitized, 'N39.3은 보상 제외로 판단됩니다.');
  assert.match(panelHtml, /구조화 검토 경로/);
  assert.match(panelHtml, /진단코드 검토/);
});

test('treats facts and clarification questions as renderable graph payload', () => {
  assert.equal(hasRenderableGraphPayload({ facts: [{ subject: 'N39.3' }] }), true);
  assert.equal(
    hasRenderableGraphPayload({ plan: { clarification_questions: ['어느 실손 세대 기준인지 확인해 주세요.'] } }),
    true,
  );
  assert.match(renderGraphFactsHtml({ facts: [{ subject: 'N39.3', relation: 'EXCLUDES', object: '보상 제외' }] }), /구조화 근거/);
});

test('renders canonical policy decision with Korean labels and structured follow-ups', () => {
  const graph = {
    canonical_decision: {
      status_label: '추가 확인 필요',
      summary: '일반 탈모만으로 보상 여부를 확정할 수 없습니다.',
      authority_note: '4세대 자사 약관 직접 근거입니다.',
      conditions: ['노화현상으로 인한 탈모', '비급여 의료비', '업무 또는 일상생활 지장 여부'],
    },
    plan: {
      clarification_questions: ['노화현상인지 질병성 탈모인지 확인해 주세요.'],
      required_evidence: ['진단명 또는 진단코드', '의사소견'],
    },
  };

  const canonicalHtml = renderCanonicalDecisionHtml(graph);
  const clarificationHtml = renderClarificationHtml(graph);

  assert.match(canonicalHtml, /추가 확인 필요/);
  assert.match(canonicalHtml, /4세대 자사 약관/);
  assert.doesNotMatch(canonicalHtml, /claim_condition_review/);
  assert.match(clarificationHtml, /진단명 또는 진단코드/);
  assert.match(clarificationHtml, /의사소견/);
});
