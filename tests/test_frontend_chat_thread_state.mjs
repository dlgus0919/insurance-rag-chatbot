import test from 'node:test';
import assert from 'node:assert/strict';

import { createChatThreadState } from '../frontend/js/modules/chat-thread-state.js';

test('ignores a late history response after another session is selected', () => {
  const state = createChatThreadState();
  const first = state.beginLoad('session-a');
  const second = state.beginLoad('session-b');

  assert.equal(state.canCommit(first), false);
  assert.equal(state.canCommit(second), true);
  assert.equal(state.activeSessionId(), 'session-b');
});

test('mode changes do not replace the active thread', () => {
  const state = createChatThreadState();
  const load = state.beginLoad('session-a');
  state.commitLoad(load);

  state.setInputMode('claim');
  state.setInputMode('general');

  assert.equal(state.activeSessionId(), 'session-a');
  assert.equal(state.inputMode(), 'general');
});

test('invalidates an in-flight request when the active session changes', () => {
  const state = createChatThreadState();
  const first = state.beginLoad('session-a');
  const requestRevision = state.currentRevision();

  state.beginLoad('session-b');

  assert.equal(state.isCurrentRequest('session-a', requestRevision), false);
  assert.equal(state.isCurrentRequest('session-b', state.currentRevision()), true);
  assert.equal(first.revision < state.currentRevision(), true);
});
