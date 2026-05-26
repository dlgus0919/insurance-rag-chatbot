import { API_CONFIG } from './config.js';

// ===== 날짜 포맷팅 =====
export function formatDate(date, format = 'YYYY-MM-DD HH:mm') {
  const d = new Date(date);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hours = String(d.getHours()).padStart(2, '0');
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const seconds = String(d.getSeconds()).padStart(2, '0');

  return format
    .replace('YYYY', year)
    .replace('MM', month)
    .replace('DD', day)
    .replace('HH', hours)
    .replace('mm', minutes)
    .replace('ss', seconds);
}

export function formatTime(date) {
  return formatDate(date, 'HH:mm');
}

export function formatShortDate(date) {
  return formatDate(date, 'YYYY-MM-DD');
}

// ===== 텍스트 유효성 검사 =====
export function isValidEmail(email) {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

export function isValidPassword(password) {
  return password && password.length >= 6;
}

export function isBlank(value) {
  return !value || (typeof value === 'string' && value.trim() === '');
}

export function isEmpty(value) {
  if (Array.isArray(value)) return value.length === 0;
  if (value && typeof value === 'object') return Object.keys(value).length === 0;
  return isBlank(value);
}

// ===== 텍스트 포맷팅 =====
export function truncate(text, maxLength = 50, ellipsis = '...') {
  if (!text) return '';
  return text.length > maxLength ? text.slice(0, maxLength) + ellipsis : text;
}

export function capitalize(text) {
  if (!text) return '';
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));
}

// ===== API Fetch =====
export async function apiFetch(path, options = {}) {
  const request = {
    credentials: 'include',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  };

  let response = await fetch(API_CONFIG.BASE_URL + path, request);
  if (response.status === 401) {
    const refreshed = await fetch(API_CONFIG.BASE_URL + '/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    }).catch(() => null);

    if (refreshed?.ok) {
      response = await fetch(API_CONFIG.BASE_URL + path, request);
    }
  }

  if (!response.ok) {
    let message = '요청 처리 중 오류가 발생했습니다.';
    try {
      const data = await response.json();
      message = data?.error?.message || data.detail || data.message || message;
    } catch {
      // Ignore non-JSON error responses.
    }
    throw new Error(message);
  }

  return response;
}

// ===== 배열 유틸 =====
export function unique(array) {
  return [...new Set(array)];
}

export function chunk(array, size) {
  const chunks = [];
  for (let i = 0; i < array.length; i += size) {
    chunks.push(array.slice(i, i + size));
  }
  return chunks;
}

export function pick(obj, keys) {
  return keys.reduce((acc, key) => {
    if (key in obj) acc[key] = obj[key];
    return acc;
  }, {});
}

// ===== 디바운스 & 쓰로틀 =====
export function debounce(func, delay = 300) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), delay);
  };
}

export function throttle(func, limit = 300) {
  let lastCall = 0;
  return function (...args) {
    const now = Date.now();
    if (now - lastCall >= limit) {
      lastCall = now;
      func(...args);
    }
  };
}

// ===== 기타 =====
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function generateId() {
  return `${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
}

export function cloneDeep(obj) {
  return JSON.parse(JSON.stringify(obj));
}

// ===== SSE 파싱 =====
export async function readSse(reader, onEvent) {
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      const event = (part.match(/^event: (.+)$/m) || [])[1];
      const raw = (part.match(/^data: ([\s\S]*)$/m) || [])[1] || '';
      let data = raw;
      try {
        data = JSON.parse(raw);
      } catch {
        // Keep raw string.
      }
      onEvent({ event, data });
    }
  }
}

// ===== 출처 포맷팅 =====
export function formatSource(source) {
  if (typeof source === 'string') return source;
  const name = source.filename || source.source || source.title || '출처';
  return source.page ? `${name} (p.${source.page})` : name;
}

// ===== DOM 유틸 =====
export function setTableLoading(tbody, colspan) {
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="${colspan}" class="table-loading">로딩 중...</td></tr>`;
}
