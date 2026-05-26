import {
  fetchAllUsers,
  createUser,
  changeUserStatus,
  deleteUser,
  resetUserPassword,
  fetchAuditLogs,
  fetchSystemStats,
  normalizeListResponse,
} from '../modules/admin.js';
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

export async function loadAdminDashboard() {
  await Promise.all([
    loadAdminLogs().catch(() => null),
    loadAdminStats().catch(() => null),
    loadAdminUsers().catch(() => null),
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
  const cards = document.querySelectorAll('#sub-stats .stat-val');
  cards.forEach((card) => {
    card.textContent = '...';
  });

  const data = await fetchSystemStats();
  if (cards[0]) cards[0].textContent = data.total_queries || 0;
  if (cards[1]) cards[1].textContent = data.total_queries || 0;

  const distribution = data.mode_distribution || {};
  const total = Math.max(1, Object.values(distribution).reduce((sum, count) => sum + Number(count || 0), 0));
  const bars = document.querySelectorAll('#sub-stats .chart-card:last-child div[style*="width"]');
  ['general', 'quickcode', 'formal'].forEach((key, index) => {
    if (bars[index]) bars[index].style.width = Math.round((distribution[key] || 0) * 100 / total) + '%';
  });
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

  try {
    await createUser(payload);
    closeModal('modal-add');
    toast('사용자가 추가되었습니다.');
    await loadAdminUsers();
  } catch (error) {
    toast(error.message, 'error');
  }
}

export async function resetPasswordFromModal() {
  const targetUserId = getResetTargetUser();
  const password = document.getElementById('reset-password')?.value;
  if (!targetUserId) {
    toast('대상 사용자가 없습니다.', 'error');
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
  const page = document.getElementById('page-admin');
  if (!page || page.dataset.phase3Delegated) return;

  page.dataset.phase3Delegated = 'true';
  page.addEventListener('click', async (event) => {
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
  });
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
  if (sub === 'logs' || sub === 'stats' || sub === 'users') await loadAdminDashboard();
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
