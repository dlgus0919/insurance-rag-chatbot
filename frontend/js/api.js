import { API_CONFIG } from './config.js';
import { getToken } from './storage.js';

// ===== 기본 Fetch 함수 =====
export async function fetchAPI(endpoint, options = {}) {
  const url = `${API_CONFIG.BASE_URL}${endpoint}`;
  const defaultHeaders = { 'Content-Type': 'application/json' };
  const token = getToken();

  if (token) {
    defaultHeaders.Authorization = `Bearer ${token}`;
  }

  const config = {
    credentials: 'include',
    ...options,
    headers: {
      ...defaultHeaders,
      ...(options.headers || {}),
    },
  };

  try {
    const response = await Promise.race([
      fetch(url, config),
      new Promise((_, reject) => setTimeout(() => reject(new Error('API timeout')), API_CONFIG.TIMEOUT)),
    ]);

    if (!response.ok) {
      const message = await readErrorMessage(response);
      const error = new Error(message || `HTTP ${response.status}`);
      error.status = response.status;
      error.response = response;
      throw error;
    }

    if (response.status === 204) return null;

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) return null;

    return await response.json();
  } catch (error) {
    console.error(`API Error [${endpoint}]:`, error);
    throw error;
  }
}

async function readErrorMessage(response) {
  try {
    const data = await response.json();
    if (typeof data?.error?.message === 'string') return data.error.message;
    if (typeof data?.message === 'string') return data.message;
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail)) {
      return data.detail.map(formatValidationDetail).filter(Boolean).join('\n');
    }
  } catch {
    // Ignore non-JSON error responses.
  }
  return `HTTP ${response.status}`;
}

function formatValidationDetail(detail) {
  const field = Array.isArray(detail?.loc) ? detail.loc.filter((part) => part !== 'body').join('.') : '';
  const message = detail?.msg || '입력값이 올바르지 않습니다.';
  return field ? `${field}: ${message}` : message;
}

// ===== 인증 관련 API =====
export function loginUser(username, password) {
  return fetchAPI(API_CONFIG.ENDPOINTS.LOGIN, {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function logoutUser() {
  return fetchAPI(API_CONFIG.ENDPOINTS.LOGOUT, { method: 'POST' });
}

export function refreshToken() {
  return fetchAPI(API_CONFIG.ENDPOINTS.REFRESH, { method: 'POST' });
}

// ===== 채팅 관련 API =====
export function getChatSessions() {
  return fetchAPI(API_CONFIG.ENDPOINTS.CHAT_SESSIONS);
}

export function createChatSession(title = '새 대화') {
  return fetchAPI(API_CONFIG.ENDPOINTS.CHAT_SESSIONS_CREATE, {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
}

export function deleteChatSession(sessionId) {
  return fetchAPI(API_CONFIG.ENDPOINTS.CHAT_SESSIONS_DELETE.replace('{id}', encodeURIComponent(sessionId)), {
    method: 'DELETE',
  });
}

export function sendChatMessage(sessionId, message) {
  return fetchAPI(API_CONFIG.ENDPOINTS.CHAT_STREAM, {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message }),
  });
}

export function getMessages(sessionId) {
  return fetchAPI(API_CONFIG.ENDPOINTS.CHAT_MESSAGES.replace('{id}', encodeURIComponent(sessionId)));
}

// ===== 스트리밍 API =====
export function streamChatMessage(sessionId, message, onData, onError) {
  return fetchAPI(API_CONFIG.ENDPOINTS.CHAT_STREAM, {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message, stream: true }),
  })
    .then((response) => {
      if (response.stream_url) {
        const eventSource = new EventSource(response.stream_url);
        eventSource.onmessage = (event) => onData(JSON.parse(event.data));
        eventSource.onerror = () => {
          eventSource.close();
          if (onError) onError(new Error('Stream connection closed'));
        };
        return eventSource;
      }
      return response;
    })
    .catch(onError);
}

// ===== 관리자 API =====
export function getAdminUsers() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_USERS);
}

export function getAdminSessions() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_SESSIONS);
}

export function getAdminAudit() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_AUDIT);
}
