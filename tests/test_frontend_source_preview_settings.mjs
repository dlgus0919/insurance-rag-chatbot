import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { getActiveScopeFilters, renderSourcesHtml } from '../frontend/js/pages/chat.js';

test('auto parameter toggle is inside the gear settings menu', async () => {
  const html = await readFile(new URL('../frontend/html/chat.html', import.meta.url), 'utf8');
  const menuIndex = html.indexOf('id="adaptive-k-menu"');
  const autoIndex = html.indexOf('id="auto-param-toggle-wrap"');

  assert.notEqual(menuIndex, -1);
  assert.notEqual(autoIndex, -1);
  assert.ok(menuIndex < autoIndex);
  assert.equal(html.indexOf('id="adaptive-k-toggle-wrap"'), -1);
  assert.equal(html.includes('Semi-adaptive K'), false);
  assert.match(html, /검색\/답변 자동 설정/);
});

test('source badges expose snippet text as a hover preview', () => {
  const html = renderSourcesHtml([
    {
      filename: 'sample.pdf',
      page: 12,
      snippet: '상해 입원 의료비 지급 기준에 관한 검색 청크입니다.',
    },
  ]);

  assert.match(html, /msg-sources/);
  assert.match(html, /sample\.pdf \(p\.12\)/);
  assert.match(html, /data-source-preview=/);
  assert.match(html, /상해 입원 의료비 지급 기준/);
});

test('source hover preview preserves raw display evidence whitespace and amount', () => {
  const html = renderSourcesHtml([
    {
      filename: 'sample.pdf',
      page: 12,
      snippet: '정밀영상검사  \n  계약일부터 1년간 보상한도는 200만원입니다.',
    },
  ]);

  assert.match(html, /정밀영상검사\s+계약일부터 1년간 보상한도는 200만원/);
  assert.doesNotMatch(html, /정밀영상검사계약일부터/);
});

test('PDF source badges retain the hover preview and open the cited page safely', () => {
  const docShort = '표준 약관 & 안내';
  const html = renderSourcesHtml([
    {
      filename: '표준 약관 & 안내.pdf',
      doc_short: docShort,
      page: 12,
      snippet: '해당 약관 조항의 원문 청크입니다.',
    },
  ]);

  const expectedHref = `/api/chat/sources/pdf?doc_short=${encodeURIComponent(docShort)}#page=12`;
  assert.match(html, /<a class="src-badge src-badge--link"/);
  assert.ok(html.includes(`href="${expectedHref}"`));
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /data-source-preview=/);
});

test('non-PDF or incomplete source badges stay nonclickable while retaining previews', () => {
  const nonPdf = renderSourcesHtml([
    {
      filename: '비급여 표준 모델.xlsx',
      doc_short: '비급여 표준 모델',
      page: 4,
      snippet: '스프레드시트 근거 미리보기입니다.',
    },
  ]);
  const missingPage = renderSourcesHtml([
    {
      filename: '약관.pdf',
      doc_short: '약관',
      snippet: '페이지 정보가 없는 근거 미리보기입니다.',
    },
  ]);

  assert.doesNotMatch(nonPdf, /<a\b/);
  assert.match(nonPdf, /data-source-preview=/);
  assert.doesNotMatch(missingPage, /<a\b/);
  assert.match(missingPage, /data-source-preview=/);
});

test('document scope checklist sends selected doc_short filters', () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    querySelectorAll(selector) {
      assert.equal(selector, '[data-doc-scope]:checked');
      return [
        { value: '__all__' },
        { value: '약관' },
        { value: '표준약관' },
      ];
    },
  };

  try {
    assert.deepEqual(getActiveScopeFilters(), { doc_filter: ['약관', '표준약관'] });
  } finally {
    globalThis.document = originalDocument;
  }
});

test('document scope UI is a settings checklist section', async () => {
  const html = await readFile(new URL('../frontend/html/chat.html', import.meta.url), 'utf8');

  assert.match(html, /class="settings-section doc-scope"/);
  assert.match(html, /id="doc-scope-summary"/);
  assert.match(html, /id="doc-scope-options"/);
  assert.match(html, /data-doc-scope value="__all__"/);
  assert.match(html, /data-doc-scope value="약관"/);
  assert.match(html, /data-doc-scope value="실무가이드"/);
});
