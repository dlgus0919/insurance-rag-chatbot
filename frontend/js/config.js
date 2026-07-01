// ===== API 설정 =====
const getBaseUrl = () => {
  if (typeof window !== 'undefined') {
    const explicitBaseUrl = window.__API_BASE_URL__;
    if (explicitBaseUrl) return explicitBaseUrl.replace(/\/$/, "");

    if (window.location.port === '3000') {
      return `${window.location.protocol}//${window.location.hostname}:8000/api`;
    }
  }
  return '/api';
};

export const API_CONFIG = {
  BASE_URL: getBaseUrl(),
  TIMEOUT: 30000,
  ENDPOINTS: {
    LOGIN: '/auth/login',
    LOGOUT: '/auth/logout',
    REFRESH: '/auth/refresh',
    ME: '/auth/me',
    CHAT: '/chat/stream',
    CHAT_STREAM: '/chat/stream',
    CLAIM_CALCULATE: '/claim/calculate',
    CHAT_SESSIONS: '/sessions',
    CHAT_SESSIONS_CREATE: '/sessions',
    CHAT_SESSIONS_DELETE: '/sessions/{id}',
    CHAT_MESSAGES: '/sessions/{id}/messages',
    ADMIN_USERS: '/admin/users',
    ADMIN_LOGS: '/admin/logs',
    ADMIN_STATS: '/admin/stats',
    ADMIN_SYSTEM_SUMMARY: '/admin/system-summary',
    ADMIN_RAG_DIAGNOSTICS: '/admin/rag-diagnostics/latest',
    ADMIN_GRAPH_VECTOR_SYNC: '/admin/graph-vector-sync',
    ADMIN_KNOWLEDGE_INTAKE_JOBS: '/admin/knowledge/intake/jobs',
    ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE: '/admin/knowledge/intake/jobs',
    ADMIN_KNOWLEDGE_APPLY_APPROVED: '/admin/knowledge/apply-approved',
    ADMIN_ONTOLOGY_CANDIDATES: '/admin/knowledge/ontology-candidates',
    ADMIN_RULE_CANDIDATES: '/admin/knowledge/rule-candidates',
    ADMIN_SESSIONS: '/admin/sessions',
    ADMIN_AUDIT: '/admin/audit',
    SYSTEM_MODELS: '/system/models',
  },
};

// ===== 역할 정의 =====
export const ROLES = {
  ADMIN: 'admin',
  USER: 'user',
  VIEWER: 'viewer',
};

// ===== 로컬스토리지 키 =====
export const STORAGE_KEYS = {
  TOKEN: 'auth_token',
  USER: 'user_info',
  SELECTED_LLM_MODEL: 'selected_llm_model',
  SELECTED_LLM_MODEL_SOURCE: 'selected_llm_model_source',
  QWEN_REASONING_MODE: 'qwen_reasoning_mode',
  AUTO_RAG_PARAMS: 'auto_rag_params',
  SESSIONS: 'chat_sessions',
  THEME: 'app_theme',
  PREFERENCES: 'app_preferences',
};

export const SESSION_KEYS = {
  FRESH_CHAT_NOTICE: 'chat_fresh_notice',
};

// ===== 애플리케이션 상수 =====
export const APP_CONFIG = {
  APP_NAME: '신한EZ손해보험 보상지원 AI 챗봇',
  VERSION: '1.0.7',
  POLLING_INTERVAL: 5000,
  MESSAGE_BATCH_SIZE: 50,
  SESSION_TIMEOUT: 30 * 60 * 1000,
};

// ===== 메시지 타입 =====
export const MESSAGE_TYPES = {
  USER: 'user',
  AI: 'ai',
  SYSTEM: 'system',
};

// ===== 상태 =====
export const STATUSES = {
  PENDING: 'pending',
  LOADING: 'loading',
  SUCCESS: 'success',
  ERROR: 'error',
  IDLE: 'idle',
};
