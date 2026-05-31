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
  normalizeListResponse,
} from '../modules/admin.js?v=20260531_graph_sync';
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

let adminActionRoot = null;
let adminActionClickHandler = null;

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
  const [data, graphSync] = await Promise.all([
    fetchLatestRagDiagnostics(),
    fetchGraphVectorSync({ indexMode: 'default', limit: 300 }).catch((error) => ({
      available: false,
      message: error.message || 'GraphDB 근거 정합성 진단을 불러오지 못했습니다.',
    })),
  ]);
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
  const isProtected = user.id === 'admin';
  const roleClass = user.role === 'admin' ? 'admin' : user.role === 'viewer' ? 'viewer' : 'user';
  const roleLabel = user.role === 'admin' ? '관리자' : user.role === 'viewer' ? '열람자' : '사용자';
  const statusButtonText = user.status === 'active' ? '비활성화' : '활성화';
  const nextStatus = user.status === 'active' ? 'inactive' : 'active';
  const statusButton = isProtected
    ? '<button class="act-btn dng" type="button" disabled title="admin 계정은 비활성화할 수 없습니다.">비활성화</button>'
    : `<button class="act-btn dng" type="button" data-admin-action="toggle-user-status" data-user-id="${escapeHTML(user.id)}" data-user-status="${nextStatus}">${statusButtonText}</button>`;
  const deleteButton = isProtected
    ? '<button class="act-btn del" type="button" disabled title="admin 계정은 삭제할 수 없습니다.">삭제</button>'
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
  if (!['admin', 'user', 'viewer'].includes(payload.role)) {
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
  if (userId === 'admin') {
    toast('admin 계정은 비활성화할 수 없습니다.', 'warn');
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
  if (userId === 'admin') {
    toast('admin 계정은 삭제할 수 없습니다.', 'warn');
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
  document.querySelectorAll('.a-sub').forEach((section) => section.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach((item) => item.classList.remove('active'));
  document.getElementById('sub-' + sub)?.classList.add('active');
  element?.classList.add('active');

  const title = document.getElementById('admin-ttl');
  const subTitles = { logs: '로그 조회', stats: '통계', users: '사용자 관리', system: '시스템 상태', rag: 'RAG 검색 진단' };
  if (title) title.textContent = subTitles[sub];
  if (sub === 'logs') await loadAdminLogs();
  if (sub === 'stats') await loadAdminStats();
  if (sub === 'users') await loadAdminUsers();
  if (sub === 'system') await loadSystemSummary();
  if (sub === 'rag') await loadRagDiagnostics();
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
