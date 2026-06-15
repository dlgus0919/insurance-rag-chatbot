import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatSelectedModelLabel,
  isReasoningSupportedModel,
} from '../frontend/js/pages/chat.js';

test('formats local provider model labels consistently', () => {
  assert.equal(
    formatSelectedModelLabel('ollama:llama-3.3-70b-instruct-q4-k-m'),
    'Ollama · llama-3.3-70b-instruct-q4-k-m',
  );
  assert.equal(
    formatSelectedModelLabel('sglang:qwen3-next-80b-a3b-instruct-fp8'),
    'SGLang · Qwen3 Next 80B Instruct',
  );
  assert.equal(formatSelectedModelLabel('sglang:gpt-oss-20b'), 'SGLang · GPT-OSS 20B');
});

test('reasoning toggle support remains limited to Qwen Thinking', () => {
  assert.equal(isReasoningSupportedModel('sglang:qwen3-next-80b-a3b-thinking-fp8'), true);
  assert.equal(isReasoningSupportedModel('ollama:llama-3.3-70b-instruct-q4-k-m'), false);
  assert.equal(isReasoningSupportedModel('ollama:exaone3.5:7.8b'), false);
});
