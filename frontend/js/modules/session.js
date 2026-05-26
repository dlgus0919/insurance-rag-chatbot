import { fetchAPI } from '../api.js';
import { API_CONFIG } from '../config.js';
import {
  getSessions,
  removeSession as removeSessionStorage,
  setSessions,
  updateSession,
} from '../storage.js';

let currentSessionId = null;

export async function fetchSessions() {
  try {
    const sessions = await fetchAPI(API_CONFIG.ENDPOINTS.CHAT_SESSIONS, { method: 'GET' });
    setSessions(sessions);
    return sessions;
  } catch (error) {
    console.error('Failed to fetch sessions:', error);
    return getSessions();
  }
}

export async function createSession(title = 'New Chat') {
  const session = await fetchAPI(API_CONFIG.ENDPOINTS.CHAT_SESSIONS_CREATE, {
    method: 'POST',
    body: JSON.stringify({ title }),
  });

  const sessions = getSessions();
  sessions.unshift(session);
  setSessions(sessions);
  return session;
}

export async function deleteSession(sessionId) {
  await fetchAPI(`${API_CONFIG.ENDPOINTS.CHAT_SESSIONS}/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });

  removeSessionStorage(sessionId);

  if (currentSessionId === sessionId) {
    currentSessionId = null;
  }
}

export function setCurrentSession(sessionId) {
  currentSessionId = sessionId;
}

export function getCurrentSessionId() {
  return currentSessionId;
}

export async function updateSessionTitle(sessionId, newTitle) {
  const updated = await fetchAPI(`${API_CONFIG.ENDPOINTS.CHAT_SESSIONS}/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ title: newTitle }),
  });

  updateSession(sessionId, updated);
  return updated;
}

export function getLocalSessions() {
  return getSessions();
}
