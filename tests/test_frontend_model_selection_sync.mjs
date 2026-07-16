import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  formatSelectedModelLabel,
  isReasoningSupportedModel,
} from '../frontend/js/pages/chat.js';
import { MODEL_SELECTION_SOURCES, resolveSelectedModelForAuthenticatedRoute } from '../frontend/js/modules/model-selection.js';

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
  assert.equal(isReasoningSupportedModel('ollama:example-model'), false);
});

test('restores a stale model selection to the current runtime default', () => {
  const resolved = resolveSelectedModelForAuthenticatedRoute({
    selectedModel: 'ollama:exaone3.5:7.8b',
    source: MODEL_SELECTION_SOURCES.EXPLICIT,
    availableLocalIds: ['sglang:qwen3-next-80b-a3b-instruct-fp8'],
    defaultLocal: 'sglang:qwen3-next-80b-a3b-instruct-fp8',
  });

  assert.deepEqual(resolved, {
    model: 'sglang:qwen3-next-80b-a3b-instruct-fp8',
    source: MODEL_SELECTION_SOURCES.DEFAULT,
  });
});

test('frontend runtime model UI has no static EXAONE exposure', () => {
  const sources = [
    '../frontend/html/login.html',
    '../frontend/html/chat.html',
    '../frontend/html/admin.html',
    '../frontend/js/pages/chat.js',
  ].map((path) => readFileSync(new URL(path, import.meta.url), 'utf8'));

  assert.match(sources[0], /기동 중인 LLM/);
  assert.match(sources[1], /기동 중인 LLM/);
  assert.doesNotMatch(sources.join('\n'), /exaone3\.5:7\.8b/i);
});

test('admin system summary renders running models instead of installed model candidates', () => {
  const adminSource = readFileSync(new URL('../frontend/js/pages/admin.js', import.meta.url), 'utf8');

  assert.match(adminSource, /llm\.running_models/);
  assert.doesNotMatch(adminSource, /llm\.available_models/);
});
