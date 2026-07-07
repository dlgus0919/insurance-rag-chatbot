import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('claim generation UI defaults to the latest supported generation', async () => {
  const html = await readFile(new URL('../frontend/html/chat.html', import.meta.url), 'utf8');
  const js = await readFile(new URL('../frontend/js/pages/chat.js', import.meta.url), 'utf8');

  assert.match(html, /value="5th" checked/);
  assert.doesNotMatch(html, /value="4th" checked/);
  assert.match(js, /claim-policy-generation"\]\[value="5th"/);
  assert.match(js, /\?\.value \|\| '5th'/);
});
