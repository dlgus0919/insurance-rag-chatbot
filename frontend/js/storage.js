import { STORAGE_KEYS } from './config.js';

// ===== 토큰 관리 =====
export function getToken() {
  return localStorage.getItem(STORAGE_KEYS.TOKEN);
}

export function setToken(token) {
  localStorage.setItem(STORAGE_KEYS.TOKEN, token);
}

export function removeToken() {
  localStorage.removeItem(STORAGE_KEYS.TOKEN);
}

export function hasToken() {
  return !!getToken();
}

// ===== 사용자 정보 관리 =====
export function getUser() {
  const user = localStorage.getItem(STORAGE_KEYS.USER);
  if (!user) return null;
  try {
    return JSON.parse(user);
  } catch {
    localStorage.removeItem(STORAGE_KEYS.USER);
    return null;
  }
}

export function setUser(user) {
  localStorage.setItem(STORAGE_KEYS.USER, JSON.stringify(user));
}

export function removeUser() {
  localStorage.removeItem(STORAGE_KEYS.USER);
}

// ===== 세션 관리 =====
export function getSessions() {
  const sessions = localStorage.getItem(STORAGE_KEYS.SESSIONS);
  return sessions ? JSON.parse(sessions) : [];
}

export function setSessions(sessions) {
  localStorage.setItem(STORAGE_KEYS.SESSIONS, JSON.stringify(sessions));
}

export function addSession(session) {
  const sessions = getSessions();
  sessions.push(session);
  setSessions(sessions);
}

export function removeSession(sessionId) {
  const sessions = getSessions();
  setSessions(sessions.filter((session) => session.id !== sessionId));
}

export function updateSession(sessionId, updates) {
  const sessions = getSessions();
  const index = sessions.findIndex((session) => session.id === sessionId);
  if (index !== -1) {
    sessions[index] = { ...sessions[index], ...updates };
    setSessions(sessions);
  }
}

// ===== 테마 관리 =====
export function getTheme() {
  return localStorage.getItem(STORAGE_KEYS.THEME) || 'light';
}

export function setTheme(theme) {
  localStorage.setItem(STORAGE_KEYS.THEME, theme);
}

// ===== 사용자 설정 =====
export function getPreferences() {
  const prefs = localStorage.getItem(STORAGE_KEYS.PREFERENCES);
  return prefs ? JSON.parse(prefs) : {};
}

export function setPreferences(preferences) {
  localStorage.setItem(STORAGE_KEYS.PREFERENCES, JSON.stringify(preferences));
}

export function updatePreferences(updates) {
  setPreferences({ ...getPreferences(), ...updates });
}

// ===== 전체 초기화 =====
export function clearAll() {
  localStorage.clear();
}

export function clearAuth() {
  removeToken();
  removeUser();
}
