import { API_CONFIG } from '../config.js';
import { fetchAPI } from '../api.js?v=20260528_admin_user_validation';

const DEFAULT_PAGE_SIZE = 100;

function buildQuery(params = {}) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, value);
  });

  const serialized = query.toString();
  return serialized ? `?${serialized}` : '';
}

function buildEndpoint(endpoint, params) {
  return `${endpoint}${buildQuery(params)}`;
}

export function fetchAllUsers(options = {}) {
  return fetchAPI(buildEndpoint(API_CONFIG.ENDPOINTS.ADMIN_USERS, {
    page: options.page || 1,
    page_size: options.pageSize || options.page_size || DEFAULT_PAGE_SIZE,
    role: options.role,
    status: options.status,
    search: options.search,
  }));
}

export function createUser(payload) {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_USERS, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateUser(userId, updates) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_USERS}/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export function changeUserRole(userId, newRole) {
  return updateUser(userId, { role: newRole });
}

export function changeUserStatus(userId, status) {
  return updateUser(userId, { status });
}

export function deleteUser(userId) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_USERS}/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
}

export function resetUserPassword(userId, newPassword) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_USERS}/${encodeURIComponent(userId)}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  });
}

export function fetchAllSessions(options = {}) {
  return fetchAPI(buildEndpoint(API_CONFIG.ENDPOINTS.ADMIN_SESSIONS, {
    page: options.page || 1,
    page_size: options.pageSize || options.page_size || DEFAULT_PAGE_SIZE,
    user_id: options.userId || options.user_id,
    search: options.search,
  }));
}

export function terminateSession(sessionId) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_SESSIONS}/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
}

export function fetchAuditLogs(options = {}) {
  return fetchAPI(buildEndpoint(API_CONFIG.ENDPOINTS.ADMIN_LOGS, {
    page: options.page || 1,
    page_size: options.pageSize || options.page_size || 50,
    user_id: options.userId || options.user_id,
    event_type: options.eventType || options.event_type,
    from: options.from,
    to: options.to,
  }));
}

export async function exportAuditLogs(options = {}) {
  const data = await fetchAuditLogs({
    ...options,
    pageSize: options.pageSize || options.page_size || 200,
  });
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });

  return {
    blob,
    filename: options.filename || `audit_logs_${new Date().toISOString().slice(0, 10)}.json`,
    data,
  };
}

export function fetchSystemStats() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_STATS);
}

export function fetchSystemSummary() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_SYSTEM_SUMMARY);
}

export function fetchLatestRagDiagnostics() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_RAG_DIAGNOSTICS);
}

export function fetchGraphVectorSync(options = {}) {
  return fetchAPI(buildEndpoint(API_CONFIG.ENDPOINTS.ADMIN_GRAPH_VECTOR_SYNC, {
    index_mode: options.indexMode || options.index_mode || 'v2_only',
    limit: options.limit || 300,
    seed: options.seed,
  }));
}

export function fetchKnowledgeIntakeJobs() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_JOBS);
}

export function createKnowledgeIntakeJob(file) {
  const formData = new FormData();
  formData.append('file', file);
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_JOBS, {
    method: 'POST',
    body: formData,
  });
}

export function runKnowledgeIntakeJob(jobId) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_JOBS}/${encodeURIComponent(jobId)}/run`, {
    method: 'POST',
  });
}

export function fetchKnowledgeIntakeAudit(jobId) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_INTAKE_AUDIT_BASE}/${encodeURIComponent(jobId)}/audit`);
}

export function fetchOntologyCandidates() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_ONTOLOGY_CANDIDATES);
}

export function decideOntologyCandidate(candidateId, decision, reason, holdReasonCodes = []) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_ONTOLOGY_CANDIDATES}/${encodeURIComponent(candidateId)}/decision`, {
    method: 'POST',
    body: JSON.stringify({
      decision,
      reason,
      hold_reason_codes: holdReasonCodes,
    }),
  });
}

export function fetchRuleCandidates() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_RULE_CANDIDATES);
}

export function decideRuleCandidate(candidateId, decision, reason) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_RULE_CANDIDATES}/${encodeURIComponent(candidateId)}/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, reason }),
  });
}

export function applyApprovedKnowledge() {
  return fetchAPI(API_CONFIG.ENDPOINTS.ADMIN_KNOWLEDGE_APPLY_APPROVED, {
    method: 'POST',
  });
}

export function normalizeListResponse(response) {
  if (Array.isArray(response)) {
    return {
      total: response.length,
      page: 1,
      page_size: response.length,
      items: response,
    };
  }

  return {
    total: Number(response?.total || response?.items?.length || 0),
    page: Number(response?.page || 1),
    page_size: Number(response?.page_size || response?.items?.length || 0),
    items: Array.isArray(response?.items) ? response.items : [],
  };
}
