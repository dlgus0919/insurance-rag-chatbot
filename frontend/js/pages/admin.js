import {
  fetchAllUsers,
  createUser,
  changeUserStatus,
  deleteUser,
  resetUserPassword,
  fetchAuditLogs,
  fetchSystemStats,
  fetchSystemSummary,
  fetchLatestRagDiagnostics,
  fetchGraphVectorSync,
  fetchKnowledgeIntakeJobs,
  createKnowledgeIntakeJob,
  runKnowledgeIntakeJob,
  fetchKnowledgeIntakeAudit,
  fetchActiveRules,
  fetchOntologyCandidates,
  decideOntologyCandidate,
  fetchRuleCandidates,
  decideRuleCandidate,
  applyApprovedKnowledge,
  normalizeListResponse,
} from '../modules/admin.js?v=20260531_graph_sync';
import {
  activateAdminGraphPage,
  deactivateAdminGraphPage,
  disposeAdminGraphPage,
} from './admin-graph.js';
import { fetchCurrentUser, getCurrentUser } from '../modules/auth.js';
import { createAlertModal, createConfirmModal } from '../modules/modal.js';
import { closeModal, getResetTargetUser, openModal, setResetTargetUser, toast } from '../modules/ui.js';
import { escapeHTML, setTableLoading } from '../utils.js';

export {
  fetchAllUsers,
  createUser,
  changeUserStatus,
  resetUserPassword,
  deleteUser,
  fetchAuditLogs,
  fetchSystemStats,
  fetchSystemSummary,
  fetchLatestRagDiagnostics,
  fetchGraphVectorSync,
  fetchKnowledgeIntakeJobs,
  createKnowledgeIntakeJob,
  runKnowledgeIntakeJob,
  fetchKnowledgeIntakeAudit,
  fetchActiveRules,
  fetchOntologyCandidates,
  decideOntologyCandidate,
  fetchRuleCandidates,
  decideRuleCandidate,
  applyApprovedKnowledge,
  normalizeListResponse,
};

export async function initAdminPage({ isUserAdmin, onLogout, onGoChat } = {}) {
  if (isUserAdmin && !isUserAdmin()) {
    createAlertModal('접근 거부', '관리자 권한이 없습니다.', onGoChat || null).show();
    return;
  }

  setupAdminTabs();
  setupAdminMenuHandlers({ onLogout, onGoChat });
  setupAdminActionHandlers();

  await loadAdminDashboard();
}

export function disposeAdminPage() {
  disposeAdminGraphPage();
  if (adminActionRoot && adminActionClickHandler) {
    adminActionRoot.removeEventListener('click', adminActionClickHandler);
  }
  adminActionRoot = null;
  adminActionClickHandler = null;
}

let adminActionRoot = null;
let adminActionClickHandler = null;
let currentAdminUserId = null;
let activeAdminIds = new Set();

export async function loadAdminDashboard() {
  await Promise.all([
    loadAdminLogs().catch(() => null),
    loadAdminStats().catch(() => null),
    loadAdminUsers().catch(() => null),
    loadSystemSummary().catch(() => null),
    loadRagDiagnostics().catch(() => null),
  ]);
}

async function loadAdminLogs() {
  const tbody = document.querySelector('#sub-logs tbody');
  const badge = document.querySelector('#sub-logs .cnt-badge');
  if (!tbody) return;

  setTableLoading(tbody, 6);
  const data = normalizeListResponse(await fetchAuditLogs({ page: 1, pageSize: 20 }));
  if (badge) badge.textContent = '총 ' + data.total + '건';
  tbody.innerHTML = data.items.map((item) => {
    const eventType = item.event_type || item.action || '-';
    const detail = item.detail || item.details || {};
    const createdAt = item.created_at || item.timestamp;
    const displayTime = createdAt ? new Date(createdAt).toLocaleString('ko-KR') : '-';

    return `
      <tr>
        <td>${escapeHTML(displayTime)}</td>
        <td><span class="etag ${eventClass(eventType)}">${escapeHTML(eventType)}</span></td>
        <td>${escapeHTML(item.user_id || '')}</td>
        <td>${escapeHTML(detail.role || '-')}</td>
        <td>${escapeHTML(detail.session_id || '')}</td>
        <td style="font-size:11px;color:var(--gray);">${escapeHTML(JSON.stringify(detail))}</td>
      </tr>`;
  }).join('');
}

async function loadAdminStats() {
  const data = await fetchSystemStats();
  const container = document.getElementById('sub-stats');
  if (!container) return;
  const modeDistribution = data.mode_distribution || {};
  const userDistribution = data.user_distribution || {};
  const modelDistribution = data.model_distribution || {};
  container.innerHTML = `
    <div class="stat-grid">
      ${renderMetricCard('누적 질문', formatNumber(data.total_queries || 0))}
      ${renderMetricCard('누적 응답', formatNumber(data.total_answers || 0))}
      ${renderMetricCard('평균 응답(초)', formatFloat(data.avg_elapsed_sec || 0))}
      ${renderMetricCard('평균 근거 수', formatFloat(data.avg_source_count || 0))}
    </div>
    ${renderSimpleBarChart('사용자별 질문 수', userDistribution)}
    ${renderModeChart(modeDistribution)}
    ${renderSimpleBarChart('모델별 질의 수', modelDistribution)}
  `;
}

async function loadAdminUsers() {
  const tbody = document.querySelector('#sub-users tbody');
  const badge = document.querySelector('#sub-users .cnt-badge');
  if (!tbody) return;

  setTableLoading(tbody, 7);
  const data = normalizeListResponse(await fetchAllUsers({ page: 1, pageSize: 100 }));
  let currentUser = null;
  try {
    currentUser = await fetchCurrentUser();
  } catch {
    currentUser = getCurrentUser();
  }
  currentAdminUserId = currentUser?.username || currentUser?.id || null;
  activeAdminIds = new Set(
    data.items
      .filter((user) => user.role === 'admin' && user.status === 'active')
      .map((user) => user.id)
  );
  if (badge) badge.textContent = '총 ' + data.total + '명';
  tbody.innerHTML = data.items.map(renderUserRow).join('');
}

async function loadSystemSummary() {
  const container = document.getElementById('sub-system');
  if (!container) return;
  const data = await fetchSystemSummary();
  const indices = Array.isArray(data.indices) ? data.indices : [];
  const assets = data.assets || {};
  const llm = data.llm || {};
  const embedding = data.embedding || {};
  container.innerHTML = `
    <div class="sys-grid">
      <div class="sys-card">
        <h3>인덱스</h3>
        ${indices.map((item) => `
          <div class="sys-row"><span class="sys-k">${escapeHTML(item.label)}</span><span class="sys-v ${item.bm25_exists && item.chroma_sqlite_exists ? 'ok' : 'err'}">${item.bm25_exists && item.chroma_sqlite_exists ? '정상' : '미완전'}</span></div>
          <div class="sys-row"><span class="sys-k">BM25</span><span class="sys-v">${escapeHTML(item.bm25_path)}</span></div>
          <div class="sys-row"><span class="sys-k">Chroma</span><span class="sys-v">${escapeHTML(item.chroma_dir)}</span></div>
        `).join('')}
      </div>
      <div class="sys-card">
        <h3>핵심 자산</h3>
        ${renderSystemFlagRow('chunks.jsonl', assets.chunks)}
        ${renderSystemFlagRow('GraphDB', assets.graph)}
        ${renderSystemFlagRow('표준코드 DB', assets.relational)}
        ${renderSystemFlagRow('users.json', assets.users)}
      </div>
      <div class="sys-card">
        <h3>LLM</h3>
        <div class="sys-row"><span class="sys-k">Ollama 허용</span><span class="sys-v ${llm.ollama_allowed ? 'ok' : 'err'}">${String(Boolean(llm.ollama_allowed))}</span></div>
        <div class="sys-row"><span class="sys-k">기본 Ollama</span><span class="sys-v">${escapeHTML(llm.default_local_model || '-')}</span></div>
        <div class="sys-row"><span class="sys-k">기본 vLLM</span><span class="sys-v">${escapeHTML(llm.default_vllm_model || '-')}</span></div>
        <div class="sys-row"><span class="sys-k">기본 SGLang</span><span class="sys-v">${escapeHTML(llm.default_sglang_model || '-')}</span></div>
        <div class="sys-row"><span class="sys-k">기본 OpenAI</span><span class="sys-v">${escapeHTML(llm.default_openai_model || '-')}</span></div>
      </div>
      <div class="sys-card">
        <h3>임베딩 / 모델 목록</h3>
        <div class="sys-row"><span class="sys-k">임베딩 모델</span><span class="sys-v">${escapeHTML(embedding.model || '-')}</span></div>
        <div class="sys-row"><span class="sys-k">HF 다운로드</span><span class="sys-v ${embedding.hf_model_download ? 'ok' : 'err'}">${String(Boolean(embedding.hf_model_download))}</span></div>
        <div class="sys-row"><span class="sys-k">클라우드 배포</span><span class="sys-v ${embedding.cloud_deploy ? 'ok' : 'err'}">${String(Boolean(embedding.cloud_deploy))}</span></div>
        <div class="code-blk">${escapeHTML(JSON.stringify(llm.available_models || {}, null, 2))}</div>
      </div>
    </div>
  `;
}

async function loadRagDiagnostics() {
  const container = document.getElementById('sub-rag');
  if (!container) return;
  const data = await fetchLatestRagDiagnostics();
  const graphIndexMode = data?.effective_index_mode || data?.index_mode || 'v2_only';
  const graphSync = await fetchGraphVectorSync({ indexMode: graphIndexMode, limit: 300 }).catch((error) => ({
    available: false,
    message: error.message || 'GraphDB 근거 정합성 진단을 불러오지 못했습니다.',
  }));
  const intro = `
    <div class="rag-info">최근 일반 질의의 실제 검색 단계 요약입니다.</div>
    <div class="rag-note">(퀵 코드·약관 정형 모드는 진단 데이터를 수집하지 않습니다.)</div>
  `;
  const graphSyncPanel = renderGraphVectorSyncPanel(graphSync);
  if (!data?.available) {
    container.innerHTML = `
      ${intro}
      ${graphSyncPanel}
      <div class="data-card" style="margin-top:14px;">
        <div class="data-card-hd"><h3>최근 RAG 검색 진단</h3></div>
        <div style="padding:16px 18px;font-size:13px;color:var(--gray);">${escapeHTML(data?.message || '아직 검색 진단 데이터가 없습니다.')}</div>
      </div>
    `;
    return;
  }

  const steps = Array.isArray(data.steps) ? data.steps : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings : [];
  container.innerHTML = `
    ${intro}
    ${graphSyncPanel}
    <div class="data-card" style="margin-top:14px;">
      <div class="data-card-hd"><h3>최근 RAG 검색 진단</h3></div>
      <div style="padding:14px 18px 4px 18px;font-size:12px;color:var(--gray);">
        <div><strong>질의</strong>: ${escapeHTML(data.query_preview || '-')}</div>
        <div><strong>모델</strong>: ${escapeHTML(data.model || '-')} / <strong>인덱스</strong>: ${escapeHTML(data.effective_index_mode || data.index_mode || '-')}</div>
        <div><strong>시각</strong>: ${escapeHTML(formatDateTime(data.created_at))}</div>
      </div>
      ${renderRagUnderstandingPanel(data)}
      <table>
        <thead><tr><th>단계</th><th>결과</th><th>소요시간</th><th>상태</th></tr></thead>
        <tbody>
          ${steps.map(renderRagStepRow).join('')}
        </tbody>
      </table>
      ${warnings.length ? `
        <div style="padding:10px 18px 18px 18px;">
          <div style="font-size:12px;font-weight:700;margin-bottom:6px;">경고</div>
          ${warnings.map((warning) => `<div style="font-size:12px;color:var(--danger);margin-top:4px;">${escapeHTML(warning.message || warning.code || '경고')}</div>`).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

function renderRagUnderstandingPanel(data) {
  const normalized = data?.normalized_terms && typeof data.normalized_terms === 'object' ? data.normalized_terms : {};
  const candidates = Array.isArray(data?.term_correction_candidates) ? data.term_correction_candidates : [];
  const ambiguous = Array.isArray(data?.ambiguous_terms) ? data.ambiguous_terms : [];
  const questions = Array.isArray(data?.clarification_questions) ? data.clarification_questions : [];
  const reviewPathCount = Number(data?.graph_review_path_count || 0);
  if (!Object.keys(normalized).length && !candidates.length && !ambiguous.length && !questions.length && !reviewPathCount) return '';

  const normalizedRows = Object.keys(normalized).length
    ? `<div style="margin-top:6px;"><strong>정규화 용어</strong>: ${Object.entries(normalized).map(([raw, value]) => `${escapeHTML(raw)} → ${escapeHTML(value)}`).join(' / ')}</div>`
    : '';
  const ambiguousRows = ambiguous.length
    ? `<div style="margin-top:6px;"><strong>모호 조건</strong>: ${ambiguous.map(escapeHTML).join(', ')}</div>`
    : '';
  const candidateRows = candidates.length
    ? `<div style="margin-top:6px;"><strong>보정 후보</strong>: ${candidates.map((item) => `${escapeHTML(item.raw || '')} → ${escapeHTML(item.normalized || '')}`).join(' / ')}</div>`
    : '';
  const questionRows = questions.length
    ? `<div style="margin-top:6px;"><strong>확인 질문</strong><ul style="margin:4px 0 0 16px;">${questions.map((question) => `<li>${escapeHTML(question)}</li>`).join('')}</ul></div>`
    : '';
  const pathRows = reviewPathCount
    ? `<div style="margin-top:6px;"><strong>Graph review path</strong>: ${reviewPathCount}건</div>`
    : '';

  return `
    <div style="margin:8px 18px 6px 18px;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--soft-bg);font-size:12px;color:var(--navy);">
      <div style="font-weight:800;margin-bottom:4px;">질의 이해/명확화</div>
      ${normalizedRows}
      ${candidateRows}
      ${ambiguousRows}
      ${questionRows}
      ${pathRows}
    </div>
  `;
}

function renderGraphVectorSyncPanel(data) {
  if (!data?.available) {
    return `
      <div class="data-card" style="margin-top:14px;">
        <div class="data-card-hd"><h3>GraphDB 근거 정합성</h3></div>
        <div style="padding:16px 18px;font-size:13px;color:var(--gray);">${escapeHTML(data?.message || 'GraphDB 근거 정합성 진단 데이터가 없습니다.')}</div>
      </div>
    `;
  }

  const summary = data.summary || {};
  const counts = summary.status_counts || {};
  const docs = Object.entries(summary.by_doc_short || {})
    .sort((a, b) => Number(b[1]?.missing || 0) - Number(a[1]?.missing || 0))
    .slice(0, 5);
  const missing = Number(counts.missing || 0);
  const total = Number(summary.total || data.sampled_evidence_rows || 0);
  const statusClass = missing === 0 ? 'ok' : 'warn';

  return `
    <div class="data-card" style="margin-top:14px;">
      <div class="data-card-hd"><h3>GraphDB 근거 정합성</h3><span class="${statusClass}">${missing === 0 ? '정상' : '확인 필요'}</span></div>
      <div class="stat-grid" style="padding:14px 18px 0 18px;">
        ${renderMetricCard('샘플 근거', formatNumber(total))}
        ${renderMetricCard('회수율', formatPercent(summary.hit_rate))}
        ${renderMetricCard('직접 일치', formatNumber(counts.direct_hit || 0))}
        ${renderMetricCard('문서/페이지 회수', formatNumber(counts.doc_page_hit || 0))}
      </div>
      <div style="padding:8px 18px 16px 18px;font-size:12px;color:var(--gray);">
        <div><strong>인덱스</strong>: ${escapeHTML(data.index_mode || '-')}</div>
        <div><strong>Chroma</strong>: ${escapeHTML(data.chroma_dir || '-')}</div>
        <div><strong>누락</strong>: ${formatNumber(missing)}건 / fallback ID 회수 ${formatNumber(counts.fallback_hit || 0)}건</div>
        ${docs.length ? `
          <div style="margin-top:8px;"><strong>문서별 누락 상위</strong></div>
          <ul style="margin:4px 0 0 16px;">
            ${docs.map(([doc, row]) => `<li>${escapeHTML(doc)}: ${formatNumber(row.missing || 0)} / ${formatNumber(row.total || 0)}</li>`).join('')}
          </ul>
        ` : ''}
      </div>
    </div>
  `;
}

function renderUserRow(user) {
  const isSelf = currentAdminUserId && user.id === currentAdminUserId;
  const isLastActiveAdmin = user.role === 'admin' && user.status === 'active' && activeAdminIds.size <= 1 && activeAdminIds.has(user.id);
  const lockReason = isSelf
    ? '현재 로그인한 계정은 비활성화 또는 삭제할 수 없습니다.'
    : isLastActiveAdmin
      ? '마지막 활성 관리자 계정은 비활성화 또는 삭제할 수 없습니다.'
      : '';
  const roleClass = user.role === 'admin' ? 'admin' : 'user';
  const roleLabel = user.role === 'admin' ? '관리자' : '사용자';
  const statusButtonText = user.status === 'active' ? '비활성화' : '활성화';
  const nextStatus = user.status === 'active' ? 'inactive' : 'active';
  const statusButton = lockReason
    ? `<button class="act-btn dng" type="button" disabled title="${escapeHTML(lockReason)}">${statusButtonText}</button>`
    : `<button class="act-btn dng" type="button" data-admin-action="toggle-user-status" data-user-id="${escapeHTML(user.id)}" data-user-status="${nextStatus}">${statusButtonText}</button>`;
  const deleteButton = lockReason
    ? `<button class="act-btn del" type="button" disabled title="${escapeHTML(lockReason)}">삭제</button>`
    : `<button class="act-btn del" type="button" data-admin-action="delete-user" data-user-id="${escapeHTML(user.id)}">삭제</button>`;

  return `
    <tr>
      <td>${escapeHTML(user.id)}</td>
      <td>${escapeHTML(user.username)}</td>
      <td>${escapeHTML(user.email || '-')}</td>
      <td><span class="rbadge ${roleClass}">${roleLabel}</span></td>
      <td>${user.status === 'active' ? '<span class="ok">●</span> 활성' : '<span class="warn">●</span> ' + escapeHTML(user.status)}</td>
      <td>${escapeHTML(user.last_login ? user.last_login.slice(0, 10) : '-')}</td>
      <td>
        <div class="act-btns">
          <button class="act-btn" type="button" data-admin-action="reset-password" data-user-id="${escapeHTML(user.id)}">PW 초기화</button>
          ${statusButton}
          ${deleteButton}
        </div>
      </td>
    </tr>`;
}

export async function createUserFromModal() {
  const payload = {
    user_id: document.getElementById('add-user-id')?.value.trim(),
    username: document.getElementById('add-user-name')?.value.trim(),
    email: document.getElementById('add-user-email')?.value.trim() || null,
    password: document.getElementById('add-user-password')?.value,
    role: document.getElementById('add-user-role')?.value,
  };
  const validationMessage = validateCreateUserPayload(payload);
  if (validationMessage) {
    toast(validationMessage, 'error');
    return;
  }

  try {
    await createUser(payload);
    closeModal('modal-add');
    toast('사용자가 추가되었습니다.');
    await loadAdminUsers();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function validateCreateUserPayload(payload) {
  if (!payload.user_id) return '아이디를 입력해 주세요.';
  if (!/^[A-Za-z0-9_]{3,32}$/.test(payload.user_id)) {
    return '아이디는 영문, 숫자, 밑줄(_) 조합 3~32자로 입력해 주세요.';
  }
  if (!payload.username) return '이름을 입력해 주세요.';
  if (payload.username.length > 64) return '이름은 64자 이하로 입력해 주세요.';
  if (payload.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(payload.email)) {
    return '이메일 형식을 확인해 주세요.';
  }
  if (!payload.password || payload.password.length < 8) {
    return '임시 비밀번호는 8자 이상으로 입력해 주세요.';
  }
  if (!['admin', 'user'].includes(payload.role)) {
    return '역할을 선택해 주세요.';
  }
  return '';
}

export async function resetPasswordFromModal() {
  const targetUserId = getResetTargetUser();
  const password = document.getElementById('reset-password')?.value;
  if (!targetUserId) {
    toast('대상 사용자가 없습니다.', 'error');
    return;
  }
  if (!password || password.length < 8) {
    toast('새 비밀번호는 8자 이상으로 입력해 주세요.', 'error');
    return;
  }

  try {
    await resetUserPassword(targetUserId, password);
    setResetTargetUser(null);
    closeModal('modal-reset');
    toast('비밀번호가 초기화되었습니다.');
  } catch (error) {
    toast(error.message, 'error');
  }
}

export async function setUserStatus(userId, status) {
  if (currentAdminUserId && userId === currentAdminUserId) {
    toast('현재 로그인한 계정은 비활성화할 수 없습니다.', 'warn');
    return;
  }
  if (activeAdminIds.size <= 1 && activeAdminIds.has(userId) && status !== 'active') {
    toast('마지막 활성 관리자 계정은 비활성화할 수 없습니다.', 'warn');
    return;
  }

  try {
    await changeUserStatus(userId, status);
    toast('사용자 상태가 변경되었습니다.');
    await loadAdminUsers();
  } catch (error) {
    toast(error.message, 'error');
  }
}

export async function deleteUserAccount(userId) {
  if (currentAdminUserId && userId === currentAdminUserId) {
    toast('현재 로그인한 계정은 삭제할 수 없습니다.', 'warn');
    return;
  }
  if (activeAdminIds.size <= 1 && activeAdminIds.has(userId)) {
    toast('마지막 활성 관리자 계정은 삭제할 수 없습니다.', 'warn');
    return;
  }

  createConfirmModal(
    '사용자 삭제',
    `'${userId}' 계정을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.`,
    async () => {
      try {
        await deleteUser(userId);
        toast(`사용자 '${userId}'가 삭제되었습니다.`, 'success');
        await loadAdminUsers();
      } catch (error) {
        toast(error.message || '사용자 삭제에 실패했습니다.', 'error');
      }
    },
    null
  ).show();
}

async function loadKnowledgeDashboard() {
  const tbody = document.getElementById('knowledge-job-body');
  const badge = document.getElementById('knowledge-job-count');
  if (tbody) {
    setTableLoading(tbody, 4);
    try {
      const data = normalizeListResponse(await fetchKnowledgeIntakeJobs());
      if (badge) badge.textContent = `${data.total}건`;
      tbody.innerHTML = data.items.length
        ? data.items.map(renderKnowledgeJobRow).join('')
        : '<tr><td colspan="4">등록된 문서 처리 작업이 없습니다.</td></tr>';
    } catch (error) {
      tbody.innerHTML = `<tr><td colspan="4">${escapeHTML(error.message || '문서 처리 상태를 불러오지 못했습니다.')}</td></tr>`;
    }
  }

  await Promise.all([loadActiveRules(), loadKnowledgeCandidates()]);
}

function renderKnowledgeJobRow(job) {
  return `
    <tr>
      <td>${escapeHTML(job.original_filename || '-')}</td>
      <td><span class="kb-status ${escapeHTML(job.status || '')}">${escapeHTML(formatKnowledgeStatus(job.status))}</span></td>
      <td>${escapeHTML(job.message || '')}</td>
      <td>
        <div class="act-btns">
          <button class="act-btn" type="button" data-admin-action="run-knowledge-intake" data-job-id="${escapeHTML(job.job_id || '')}">처리</button>
          <button class="act-btn" type="button" data-admin-action="load-knowledge-audit" data-job-id="${escapeHTML(job.job_id || '')}">상세</button>
        </div>
      </td>
    </tr>
  `;
}

async function uploadKnowledgeDocument() {
  const input = document.getElementById('knowledge-file-input');
  const file = input?.files?.[0];
  if (!file) {
    toast('추가할 문서를 선택하세요.', 'warn');
    return;
  }

  try {
    const job = await createKnowledgeIntakeJob(file);
    toast(`${job.original_filename || file.name} 업로드가 등록되었습니다.`, 'success');
    if (input) input.value = '';
    await loadKnowledgeDashboard();
  } catch (error) {
    toast(error.message || '문서 업로드에 실패했습니다.', 'error');
  }
}

async function runKnowledgeIntake(jobId) {
  if (!jobId) return;
  try {
    const job = await runKnowledgeIntakeJob(jobId);
    const type = String(job.status || '').startsWith('blocked') ? 'warn' : 'success';
    toast(job.message || '문서 처리가 완료되었습니다.', type);
    await loadKnowledgeDashboard();
  } catch (error) {
    toast(error.message || '문서 처리에 실패했습니다.', 'error');
  }
}

export function formatBlockReason(reason) {
  const labels = {
    scanned_pdf_text_layer_missing: 'PDF에 텍스트 레이어가 없거나 부족합니다.',
    ocr_file_unsupported: '이미지 또는 스캔 문서는 현재 자동 OCR 대상이 아닙니다.',
    unsupported_file_type: '지원하지 않는 파일 형식입니다.',
    candidate_extraction_failed: '검토 후보 생성 중 오류가 발생했습니다.',
    source_file_missing: '업로드 원본 파일을 찾을 수 없습니다.',
    excel_staging_not_ready: 'Excel 문서 구조화 staging이 아직 연결되지 않았습니다.',
  };
  return labels[reason] || (reason ? `알 수 없는 차단 사유: ${reason}` : '-');
}

export function renderAuditDetail(events) {
  if (!events.length) return '<p class="knowledge-help">기록된 감사 로그가 없습니다.</p>';
  const latest = events[events.length - 1];
  const blocked = [...events].reverse().find((event) => event.block_reason || event.event_type === 'failed');
  const blockedReason = blocked?.block_reason
    ? formatBlockReason(blocked.block_reason)
    : blocked?.event_type === 'failed'
      ? blocked.message || '-'
      : '-';
  const nextAction = blocked?.next_action
    || (blocked?.event_type === 'failed'
      ? '감사 이력과 서버 로그를 확인한 뒤 문서 처리를 다시 실행하세요.'
      : '추가 조치가 필요하지 않습니다.');
  return `
    <div class="audit-summary">
      <p><strong>현재 단계:</strong> ${escapeHTML(formatKnowledgeStatus(latest.to_status))}</p>
      <p><strong>막힌 이유:</strong> ${escapeHTML(blockedReason)}</p>
      <p><strong>다음 조치:</strong> ${escapeHTML(nextAction)}</p>
    </div>
    <ul class="audit-events">
      ${events.map((event) => `<li>${escapeHTML(event.message || formatKnowledgeStatus(event.to_status))}</li>`).join('')}
    </ul>
  `;
}

async function loadKnowledgeAudit(jobId) {
  if (!jobId) return;
  const container = document.getElementById('knowledge-audit-detail');
  if (!container) return;
  container.textContent = '감사 로그를 불러오는 중입니다...';
  try {
    const data = normalizeListResponse(await fetchKnowledgeIntakeAudit(jobId));
    container.innerHTML = renderAuditDetail(data.items);
  } catch (error) {
    container.textContent = error.message || '감사 로그를 불러오지 못했습니다.';
  }
}

async function loadActiveRules() {
  const container = document.getElementById('knowledge-active-rule-list');
  const badge = document.getElementById('knowledge-active-rule-count');
  if (!container) return;
  container.textContent = '승인된 계산 룰을 확인하는 중입니다.';
  if (badge) badge.textContent = '확인 중';
  try {
    const data = normalizeListResponse(await fetchActiveRules());
    if (badge) badge.textContent = `${data.total}건`;
    container.innerHTML = renderActiveRuleList(data.items);
  } catch (error) {
    if (badge) badge.textContent = '확인 실패';
    container.textContent = error.message || '승인된 계산 룰을 불러오지 못했습니다.';
  }
}

export function renderActiveRuleList(items) {
  if (!items.length) return '<p class="knowledge-help">승인된 액티브 룰이 없습니다.</p>';
  return items.slice(0, 100).map((rule) => {
    const values = activeRuleValues(rule);
    return `
      <article class="candidate-card">
        <div class="candidate-title">${escapeHTML(activeRuleTitle(rule))}</div>
        <div class="candidate-meta">${escapeHTML(rule.section || '-')} · ${escapeHTML(rule.rule_id || '-')}</div>
        <div class="candidate-section">
          <div class="candidate-section-label">현재 적용 값</div>
          <ul class="candidate-guide">${values.map((value) => `<li>${escapeHTML(value)}</li>`).join('')}</ul>
        </div>
        <div class="candidate-section">
          <div class="candidate-section-label">근거</div>
          <p class="candidate-text">${escapeHTML(rule.source_doc || '-')} · ${escapeHTML(rule.source_page || '-')} · ${escapeHTML(rule.source_clause || '-')}</p>
        </div>
      </article>
    `;
  }).join('');
}

function activeRuleTitle(rule) {
  return rule.description || rule.summary || rule.rule_id || '-';
}

function activeRuleValues(rule) {
  const values = [];
  const ratio = formatRulePercent(rule.copay_ratio || rule.payout_ratio);
  if (ratio) values.push(`본인부담금/지급 비율: ${ratio}`);
  if (rule.min_deductible) values.push(`최소 공제금: ${formatRuleMoney(rule.min_deductible)}`);
  if (rule.deductible_amount) values.push(`처방 공제금: ${formatRuleMoney(rule.deductible_amount)}`);
  if (rule.per_visit_limit) values.push(`회당 한도: ${formatRuleMoney(rule.per_visit_limit)}`);
  if (rule.annual_limit) values.push(`연간 한도: ${formatRuleMoney(rule.annual_limit)}`);
  if (rule.annual_visit_limit) values.push(`연간 횟수 한도: ${rule.annual_visit_limit}회`);
  if (rule.daily_limit) values.push(`일 한도: ${formatRuleMoney(rule.daily_limit)}`);
  return values.length ? values : ['표시할 수치 조건 없음'];
}

async function loadKnowledgeCandidates() {
  const container = document.getElementById('knowledge-review-summary');
  if (!container) return;
  try {
    const [ontology, rules] = await Promise.all([
      fetchOntologyCandidates().catch(() => ({ items: [] })),
      fetchRuleCandidates().catch(() => ({ items: [] })),
    ]);
    const ontologyItems = normalizeListResponse(ontology).items;
    const ruleItems = normalizeListResponse(rules).items;
    container.innerHTML = `
      <div class="candidate-columns">
        <section>
          <h4>온톨로지 후보 ${ontologyItems.length}건</h4>
          ${renderCandidateList(ontologyItems, 'ontology')}
        </section>
        <section>
          <h4>계산 룰 후보 ${ruleItems.length}건</h4>
          ${renderCandidateList(ruleItems, 'rule')}
        </section>
      </div>
    `;
  } catch (error) {
    container.textContent = error.message || '후보 목록을 불러오지 못했습니다.';
  }
}

export function renderCandidateList(items, kind) {
  if (!items.length) return '<p class="knowledge-help">검토할 후보가 없습니다.</p>';
  return items.slice(0, 100).map((item) => {
    const title = kind === 'rule'
      ? ruleCandidateTitle(item)
      : item.canonical_name || item.proposed_rule?.description || item.proposed_rule?.rule_id || item.candidate_id || '-';
    const reviewContext = kind === 'ontology'
      ? renderOntologyCandidateContext(item)
      : renderRuleCandidateContext(item);
    const candidateId = item.candidate_id || '';
    const actions = kind === 'ontology'
      ? `
        <button class="act-btn" type="button" data-admin-action="decide-ontology-candidate" data-candidate-id="${escapeHTML(candidateId)}" data-decision="approve">승인</button>
        <button class="act-btn" type="button" data-admin-action="decide-ontology-candidate" data-candidate-id="${escapeHTML(candidateId)}" data-decision="hold">보류</button>
        <button class="act-btn del" type="button" data-admin-action="decide-ontology-candidate" data-candidate-id="${escapeHTML(candidateId)}" data-decision="reject">거절</button>
      `
      : `
        <button class="act-btn" type="button" data-admin-action="decide-rule-candidate" data-candidate-id="${escapeHTML(candidateId)}" data-decision="approve">승인</button>
        <button class="act-btn del" type="button" data-admin-action="decide-rule-candidate" data-candidate-id="${escapeHTML(candidateId)}" data-decision="reject">거절</button>
      `;
    return `
      <article class="candidate-card">
        <div class="candidate-title">${escapeHTML(title)}</div>
        <div class="candidate-meta">${escapeHTML(item.status || '-')} · ${escapeHTML(candidateId || '-')}</div>
        ${reviewContext}
        <div class="candidate-actions">${actions}</div>
      </article>
    `;
  }).join('');
}

function renderOntologyCandidateContext(item) {
  const display = item.properties?.display && typeof item.properties.display === 'object'
    ? item.properties.display
    : {};
  const aliases = Array.isArray(item.candidate_aliases) ? item.candidate_aliases : [];
  const questions = Array.isArray(display.example_questions) ? display.example_questions : [];
  const similar = Array.isArray(display.similar_expressions) ? display.similar_expressions : [];
  const evidence = firstEvidence(item);
  const summary = display.summary || item.description || '후보 설명이 없습니다. 원문 근거와 승인 대상 표현을 기준으로 검토하세요.';
  const approvalPrompt = display.approval_prompt || '위 표현들을 같은 보험 업무 개념으로 묶어도 될까요?';
  const qualityNotes = ontologyQualityNotes(item);

  return `
    <div class="candidate-section">
      <div class="candidate-section-label">승인 대상 표현</div>
      ${renderInlineList(aliases, 'candidate-chip', '표시할 후보 alias가 없습니다.')}
    </div>
    <div class="candidate-section">
      <div class="candidate-section-label">설명</div>
      <p class="candidate-text">${escapeHTML(summary)}</p>
    </div>
    <div class="candidate-section">
      <div class="candidate-section-label">실무자 판단 기준</div>
      <ul class="candidate-guide">
        <li>승인: 승인 대상 표현이 후보 개념과 같은 보험 업무 개념을 가리키고, 원문 근거의 사용 맥락도 맞을 때 선택합니다.</li>
        <li>보류: 표현은 쓸 만하지만 근거, 대상 concept, 문장 조각 여부를 추가 확인해야 할 때 선택합니다.</li>
        <li>거절: 표현이 너무 넓거나 후보 개념과 연결이 잘못됐거나 단순 문장 조각일 때 선택합니다.</li>
      </ul>
    </div>
    ${qualityNotes ? `
      <div class="candidate-section candidate-warning">
        <div class="candidate-section-label">품질 경고</div>
        <p class="candidate-text">${escapeHTML(qualityNotes)}</p>
      </div>
    ` : ''}
    ${similar.length ? `
      <div class="candidate-section">
        <div class="candidate-section-label">참고 유사 표현</div>
        ${renderInlineList(similar, 'candidate-chip muted-chip', '')}
      </div>
    ` : ''}
    ${questions.length ? `
      <div class="candidate-section">
        <div class="candidate-section-label">예시 질문</div>
        <ul class="candidate-guide">${questions.slice(0, 3).map((question) => `<li>${escapeHTML(question)}</li>`).join('')}</ul>
      </div>
    ` : ''}
    <div class="candidate-section">
      <div class="candidate-section-label">원문 근거</div>
      <div class="candidate-evidence-source">${escapeHTML(evidence.sourceLabel)}</div>
      <pre>${escapeHTML(evidence.excerpt)}</pre>
    </div>
    <div class="candidate-prompt">${escapeHTML(approvalPrompt)}</div>
  `;
}

const RULE_GENERATION_LABELS = { '1th': '1세대', '2th': '2세대', '3th': '3세대', '4th': '4세대', '5th': '5세대' };
const RULE_CATEGORY_LABELS = { benefit: '급여', nonpay: '비급여', unknown: '급여/비급여 미확정' };
const RULE_VISIT_LABELS = { hospitalization: '입원', outpatient: '통원', unknown: '입원/통원 미확정' };
const RULE_FACILITY_LABELS = {
  all: '전체 의료기관',
  clinic: '의원',
  hospital: '병원',
  general_hospital: '종합병원',
  tertiary_hospital: '상급종합병원',
};

function ruleLabel(value, labels) {
  const text = String(value || '').trim();
  return labels[text] || text;
}

function formatRulePercent(value) {
  if (value === undefined || value === null || value === '') return '';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${Math.round(number * 100)}%`;
}

function formatRuleMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${number.toLocaleString('ko-KR')}원`;
}

function ruleCandidateTitle(item) {
  const rule = item.proposed_rule || {};
  const parts = [
    ruleLabel(rule.generation, RULE_GENERATION_LABELS),
    ruleLabel(rule.category, RULE_CATEGORY_LABELS),
    ruleLabel(rule.visit_type, RULE_VISIT_LABELS),
    ruleLabel(rule.facility_grade, RULE_FACILITY_LABELS),
  ].filter(Boolean);
  const ratio = formatRulePercent(rule.copay_ratio || rule.payout_ratio);
  if (ratio) parts.push(`본인부담금 ${ratio}`);
  return parts.join(' · ') || rule.description || rule.rule_id || item.candidate_id || '-';
}

function renderRuleCandidateContext(item) {
  const evidence = item.evidence_text || item.description || item.proposed_rule?.source_clause || '';
  const rule = item.proposed_rule || {};
  const condition = [
    ruleLabel(rule.generation, RULE_GENERATION_LABELS),
    ruleLabel(rule.category, RULE_CATEGORY_LABELS),
    ruleLabel(rule.visit_type, RULE_VISIT_LABELS),
    ruleLabel(rule.facility_grade, RULE_FACILITY_LABELS),
  ].filter(Boolean).join(' · ') || '-';
  const ratio = formatRulePercent(rule.copay_ratio || rule.payout_ratio) || '-';
  const minDeductible = rule.min_deductible || rule.deductible_amount || '-';
  return `
    <div class="candidate-section">
      <div class="candidate-section-label">확인할 계산 조건</div>
      <p class="candidate-text">${escapeHTML(condition)}</p>
    </div>
    <div class="candidate-section">
      <div class="candidate-section-label">제안 값</div>
      <ul class="candidate-guide">
        <li>본인부담금 비율: ${escapeHTML(ratio)}</li>
        <li>최소 공제금: ${escapeHTML(String(minDeductible))}</li>
      </ul>
    </div>
    <div class="candidate-section">
      <div class="candidate-section-label">원문 근거</div>
      <pre>${escapeHTML(String(evidence || '-').slice(0, 900))}</pre>
    </div>
  `;
}

function firstEvidence(item) {
  const evidence = Array.isArray(item.source_evidence) && item.source_evidence.length
    ? item.source_evidence[0]
    : {};
  const doc = evidence.doc_short || evidence.doc_name || evidence.source || '원문';
  const page = evidence.page ? ` · ${evidence.page}쪽` : '';
  const excerpt = item.evidence_text || evidence.excerpt || evidence.text || item.description || '-';
  return {
    sourceLabel: `${doc}${page}`,
    excerpt: String(excerpt).slice(0, 900),
  };
}

function renderInlineList(items, className, emptyText) {
  const values = items.map((item) => String(item || '').trim()).filter(Boolean).slice(0, 8);
  if (!values.length) return emptyText ? `<p class="candidate-text muted">${escapeHTML(emptyText)}</p>` : '';
  return `<div class="candidate-chip-row">${values.map((item) => `<span class="${className}">${escapeHTML(item)}</span>`).join('')}</div>`;
}

function ontologyQualityNotes(item) {
  const notes = [];
  const codexReview = item.properties?.codex_dev_review;
  const reason = codexReview?.reason || item.reason;
  const removedAliases = item.properties?.quality_repair?.removed_candidate_aliases;
  if (reason) notes.push(reason);
  if (Array.isArray(removedAliases) && removedAliases.length) {
    notes.push(`이전 정제에서 제외된 표현: ${removedAliases.slice(0, 3).join(', ')}`);
  }
  return notes.join(' / ');
}

async function decideKnowledgeCandidate(kind, candidateId, decision) {
  if (!candidateId || !decision) return;
  const reason = window.prompt('실무자 판단 사유를 입력하세요.')?.trim();
  if (reason === undefined) return;
  const finalReason = reason || '관리자 UI에서 처리';
  try {
    if (kind === 'ontology') {
      const holdCodes = decision === 'hold' ? ['needs_more_evidence'] : [];
      await decideOntologyCandidate(candidateId, decision, finalReason, holdCodes);
    } else {
      await decideRuleCandidate(candidateId, decision, finalReason);
    }
    toast('후보 처리 결과를 저장했습니다.', 'success');
    await loadKnowledgeDashboard();
  } catch (error) {
    toast(error.message || '후보 처리에 실패했습니다.', 'error');
  }
}

async function applyApprovedKnowledgeFromAdmin() {
  createConfirmModal(
    '승인 항목 반영',
    '승인된 온톨로지와 계산 룰 후보를 active 자산에 반영하고, 문서 원문 검색 인덱스(BM25/Chroma)와 GraphDB를 재빌드합니다. 계속하시겠습니까?',
    async () => {
      try {
        const result = await applyApprovedKnowledge();
        if (result?.status !== 'completed' || !result?.index_rebuilt || !result?.graph_rebuilt) {
          const detail = result?.sources?.[0]?.error || result?.rules?.error || '승인 항목 반영이 완료되지 않았습니다.';
          throw new Error(detail);
        }
        toast('승인된 지식 항목과 문서 원문 검색 인덱스를 active DB에 반영했습니다.', 'success');
        await loadKnowledgeDashboard();
      } catch (error) {
        toast(error.message || '승인 항목 반영에 실패했습니다.', 'error');
      }
    },
    null
  ).show();
}

function setupAdminTabs() {
  document.querySelectorAll('.nav-item').forEach((tab) => {
    if (tab.dataset.phase2Bound) return;

    tab.dataset.phase2Bound = 'true';
    tab.addEventListener('click', async () => {
      const sub = tab.dataset.adminSub;
      if (sub) {
        await showSub(sub, tab);
      }
    });
  });
}

function setupAdminActionHandlers() {
  const root = document.getElementById('app');
  if (!root) return;

  if (adminActionRoot && adminActionClickHandler) {
    adminActionRoot.removeEventListener('click', adminActionClickHandler);
  }

  adminActionRoot = root;
  adminActionClickHandler = async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const actionTarget = target.closest('[data-admin-action]');
    if (!actionTarget) return;

    const action = actionTarget.dataset.adminAction;

    if (action === 'export-audit') {
      toast('내보내기 완료');
    } else if (action === 'open-add-user') {
      openModal('modal-add');
    } else if (action === 'close-add-user') {
      closeModal('modal-add');
    } else if (action === 'create-user') {
      await createUserFromModal();
    } else if (action === 'reset-password') {
      openResetModal(actionTarget.dataset.userId);
    } else if (action === 'toggle-user-status') {
      await setUserStatus(actionTarget.dataset.userId, actionTarget.dataset.userStatus);
    } else if (action === 'delete-user') {
      await deleteUserAccount(actionTarget.dataset.userId);
    } else if (action === 'upload-knowledge-document') {
      await uploadKnowledgeDocument();
    } else if (action === 'run-knowledge-intake') {
      await runKnowledgeIntake(actionTarget.dataset.jobId);
    } else if (action === 'load-knowledge-audit') {
      await loadKnowledgeAudit(actionTarget.dataset.jobId);
    } else if (action === 'decide-ontology-candidate') {
      await decideKnowledgeCandidate('ontology', actionTarget.dataset.candidateId, actionTarget.dataset.decision);
    } else if (action === 'decide-rule-candidate') {
      await decideKnowledgeCandidate('rule', actionTarget.dataset.candidateId, actionTarget.dataset.decision);
    } else if (action === 'apply-approved-knowledge') {
      await applyApprovedKnowledgeFromAdmin();
    } else if (action === 'close-reset-password') {
      closeModal('modal-reset');
    } else if (action === 'confirm-reset-password') {
      await resetPasswordFromModal();
    }
  };

  root.addEventListener('click', adminActionClickHandler);
}

function setupAdminMenuHandlers({ onLogout, onGoChat }) {
  const logoutBtns = document.querySelectorAll('.admin-sidebar .logout-btn, [data-admin-action="logout"]');
  const backBtns = document.querySelectorAll('[data-admin-action="back"]');

  logoutBtns.forEach((button) => {
    if (button.dataset.phase2Bound) return;

    button.dataset.phase2Bound = 'true';
    button.addEventListener('click', () => {
      if (!onLogout) return;

      createConfirmModal(
        '로그아웃',
        '정말 로그아웃하시겠습니까?',
        onLogout,
        null
      ).show();
    });
  });

  backBtns.forEach((button) => {
    if (button.dataset.phase2Bound) return;

    button.dataset.phase2Bound = 'true';
    button.addEventListener('click', () => {
      if (onGoChat) onGoChat();
    });
  });
}

async function showSub(sub, element) {
  if (sub !== 'graph') deactivateAdminGraphPage();
  document.querySelectorAll('.a-sub').forEach((section) => section.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach((item) => item.classList.remove('active'));
  document.getElementById('sub-' + sub)?.classList.add('active');
  element?.classList.add('active');

  const title = document.getElementById('admin-ttl');
  const subTitles = { logs: '로그 조회', stats: '통계', users: '사용자 관리', system: '시스템 상태', rag: 'RAG 검색 진단', graph: 'GraphDB 탐색', knowledge: '지식 확장' };
  if (title) title.textContent = subTitles[sub];
  if (sub === 'logs') await loadAdminLogs();
  if (sub === 'stats') await loadAdminStats();
  if (sub === 'users') await loadAdminUsers();
  if (sub === 'system') await loadSystemSummary();
  if (sub === 'rag') await loadRagDiagnostics();
  if (sub === 'graph') await activateAdminGraphPage();
  if (sub === 'knowledge') await loadKnowledgeDashboard();
}

function openResetModal(userId) {
  setResetTargetUser(userId);
  const desc = document.getElementById('reset-desc');
  const input = document.getElementById('reset-password');
  if (desc) desc.textContent = `"${userId}" 계정의 비밀번호를 초기화하시겠습니까?`;
  if (input) input.value = '';
  openModal('modal-reset');
}

function eventClass(eventType) {
  const lower = String(eventType || '').toLowerCase();
  if (lower.includes('login')) return 'login';
  if (lower.includes('question')) return 'question';
  if (lower.includes('answer')) return 'answer';
  if (lower.includes('export')) return 'export';
  if (lower.includes('logout')) return 'logout';
  return 'login';
}

function renderMetricCard(label, value) {
  return `<div class="stat-card"><div class="stat-lbl">${escapeHTML(label)}</div><div class="stat-val">${escapeHTML(String(value))}</div></div>`;
}

function renderSimpleBarChart(title, distribution) {
  const rows = Object.entries(distribution || {})
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
    .slice(0, 8);
  if (!rows.length) {
    return `<div class="chart-card"><div class="chart-ttl">${escapeHTML(title)}</div><div style="font-size:12px;color:var(--gray);">데이터 없음</div></div>`;
  }
  const max = Math.max(...rows.map(([, value]) => Number(value || 0)), 1);
  return `
    <div class="chart-card">
      <div class="chart-ttl">${escapeHTML(title)}</div>
      ${rows.map(([label, value]) => `
        <div style="display:grid;grid-template-columns:140px 1fr 48px;gap:10px;align-items:center;margin-top:10px;">
          <div style="font-size:12px;">${escapeHTML(label)}</div>
          <div style="height:10px;border-radius:999px;background:var(--border);overflow:hidden;">
            <div style="height:100%;width:${Math.max(6, Math.round((Number(value || 0) / max) * 100))}%;background:var(--primary);"></div>
          </div>
          <div style="font-size:12px;text-align:right;">${escapeHTML(formatNumber(value))}</div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderModeChart(distribution) {
  const normalized = {
    general: Number(distribution?.general || 0),
    quickcode: Number(distribution?.quickcode || 0),
    formal: Number(distribution?.formal || 0),
  };
  const total = Math.max(1, Object.values(normalized).reduce((sum, value) => sum + value, 0));
  const segments = [
    ['일반 질의', normalized.general, 'var(--primary)'],
    ['퀵 코드', normalized.quickcode, 'var(--medium-blue)'],
    ['약관 정형', normalized.formal, 'var(--border)'],
  ];
  return `
    <div class="chart-card">
      <div class="chart-ttl">검색 모드 분포</div>
      <div style="display:flex;gap:14px;font-size:12px;margin-bottom:10px;flex-wrap:wrap;">
        ${segments.map(([label, value, color]) => `<span><span style="display:inline-block;width:10px;height:10px;background:${color};border-radius:2px;margin-right:5px;"></span>${escapeHTML(label)} ${Math.round((value / total) * 100)}%</span>`).join('')}
      </div>
      <div style="height:14px;border-radius:7px;overflow:hidden;display:flex;">
        ${segments.map(([, value, color]) => `<div style="width:${(value / total) * 100}%;background:${color};"></div>`).join('')}
      </div>
    </div>
  `;
}

function renderSystemFlagRow(label, enabled) {
  return `<div class="sys-row"><span class="sys-k">${escapeHTML(label)}</span><span class="sys-v ${enabled ? 'ok' : 'err'}">${enabled ? '있음' : '없음'}</span></div>`;
}

function renderRagStepRow(step) {
  const status = String(step.status || 'done');
  const statusLabel = status === 'done'
    ? '<span class="ok">✓ 완료</span>'
    : status === 'empty'
      ? '<span class="warn">⚠ 결과 없음</span>'
      : status === 'skip'
        ? '<span class="warn">⚠ 스킵</span>'
        : '<span class="warn">⚠ 확인 필요</span>';
  const elapsed = step.elapsed_ms == null ? '—' : `${(Number(step.elapsed_ms) / 1000).toFixed(2)}s`;
  return `<tr><td>${escapeHTML(step.label || '-')}</td><td style="font-size:11px;">${escapeHTML(step.result || '-')}</td><td>${escapeHTML(elapsed)}</td><td>${statusLabel}</td></tr>`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString('ko-KR');
}

function formatFloat(value) {
  return Number(value || 0).toLocaleString('ko-KR', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 1000) / 10}%`;
}

function formatDateTime(value) {
  if (!value) return '-';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('ko-KR');
}

function formatKnowledgeStatus(status) {
  const labels = {
    uploaded: '업로드됨',
    detecting_document_type: '문서 판독',
    blocked_scanned_pdf: '스캔 PDF 차단',
    blocked_unsupported: '지원 불가',
    staging_source: '원본 저장',
    building_staging_chunks: '문서 구조화',
    extracting_candidates: '후보 생성',
    waiting_review: '검토 대기',
    applying_approved: '반영 중',
    rebuilding_active: '재빌드 중',
    completed: '완료',
    failed: '실패',
  };
  return labels[status] || status || '-';
}
