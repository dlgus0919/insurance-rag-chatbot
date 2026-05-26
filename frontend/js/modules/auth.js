import { fetchAPI } from '../api.js';
import { API_CONFIG } from '../config.js';
import { getToken, getUser, removeToken, removeUser, setToken, setUser } from '../storage.js';

export function isAuthenticated() {
  return !!getToken() || !!getUser();
}

export function isTokenValid() {
  const token = getToken();
  if (!token) return false;

  try {
    const parts = token.split('.');
    if (parts.length !== 3) return false;

    const payload = JSON.parse(atob(parts[1]));
    return Date.now() < payload.exp * 1000;
  } catch {
    return false;
  }
}

export async function handleLogin(username, password) {
  const response = await fetchAPI(API_CONFIG.ENDPOINTS.LOGIN, {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });

  if (response.access_token) {
    setToken(response.access_token);
  }

  if (response.user) {
    setUser(response.user);
  }

  return response;
}

export async function handleLogout() {
  try {
    await fetchAPI(API_CONFIG.ENDPOINTS.LOGOUT, { method: 'POST' });
  } catch (error) {
    console.warn('Logout API call failed:', error);
  } finally {
    removeToken();
    removeUser();
  }
}

export async function refreshAccessToken() {
  try {
    const response = await fetchAPI(API_CONFIG.ENDPOINTS.REFRESH, { method: 'POST' });

    if (response.access_token) {
      setToken(response.access_token);
    }

    return response;
  } catch (error) {
    removeToken();
    throw error;
  }
}

export async function fetchCurrentUser() {
  const user = await fetchAPI(API_CONFIG.ENDPOINTS.ME);
  setUser(user);
  return user;
}

export function getCurrentUser() {
  return getUser();
}

export function hasRole(role) {
  const user = getUser();
  return !!user && user.role === role;
}

export function isAdmin() {
  return hasRole('admin');
}
