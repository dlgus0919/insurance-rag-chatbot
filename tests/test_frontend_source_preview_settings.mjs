import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { getActiveScopeFilters, renderSourcesHtml } from '../frontend/js/pages/chat.js';

test('auto parameter toggle is inside the gear settings menu', async () => {
  const html = await readFile(new URL('../frontend/html/chat.html', import.meta.url), 'utf8');
  const menuIndex = html.indexOf('id="adaptive-k-menu"');
  const autoIndex = html.indexOf('id="auto-param-toggle-wrap"');
  const adaptiveIndex = html.indexOf('id="adaptive-k-toggle-wrap"');

  assert.notEqual(menuIndex, -1);
  assert.notEqual(autoIndex, -1);
  assert.notEqual(adaptiveIndex, -1);
  assert.ok(menuIndex < autoIndex);
  assert.ok(autoIndex < adaptiveIndex);
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
