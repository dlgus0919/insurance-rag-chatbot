export function createChatThreadState() {
  let activeSession = '';
  let mode = 'general';
  let revision = 0;
  let loadController = null;

  return {
    beginLoad(sessionId) {
      loadController?.abort();
      loadController = new AbortController();
      activeSession = sessionId || '';
      revision += 1;
      return { sessionId: activeSession, revision, signal: loadController.signal };
    },
    canCommit(token) {
      return token.sessionId === activeSession
        && token.revision === revision
        && !token.signal.aborted;
    },
    commitLoad(token) {
      return this.canCommit(token);
    },
    currentRevision: () => revision,
    isCurrentRequest(sessionId, requestRevision) {
      return activeSession === (sessionId || '') && revision === requestRevision;
    },
    clear() {
      loadController?.abort();
      activeSession = '';
      revision += 1;
    },
    activeSessionId: () => activeSession,
    setInputMode(value) {
      mode = value === 'claim' ? 'claim' : 'general';
    },
    inputMode: () => mode,
  };
}
