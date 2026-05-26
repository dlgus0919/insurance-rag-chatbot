import { deleteSession, setCurrentSession } from './session.js';

let sidebarOpen = true;

export function toggleSidebar() {
  sidebarOpen = !sidebarOpen;

  const sidebar = document.querySelector('.sidebar');
  if (sidebar) {
    sidebar.classList.toggle('collapsed');
  }

  return sidebarOpen;
}

export function setSidebarOpen(isOpen) {
  sidebarOpen = isOpen;

  const sidebar = document.querySelector('.sidebar');
  if (!sidebar) return;

  sidebar.classList.toggle('collapsed', !isOpen);
}

export function isSidebarOpen() {
  return sidebarOpen;
}

export function renderSessionList(container, sessions, onSelectSession) {
  if (!container) return;

  container.innerHTML = '';

  sessions.forEach((session) => {
    const sessionItem = document.createElement('div');
    sessionItem.className = 'session-item history-item';
    sessionItem.setAttribute('data-session-id', session.id);

    const sessionTitle = document.createElement('span');
    sessionTitle.className = 'session-title h-title';
    sessionTitle.textContent = session.title;
    sessionItem.appendChild(sessionTitle);

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'session-delete hist-del-btn';
    deleteBtn.innerHTML = '&times;';
    deleteBtn.addEventListener('click', async (event) => {
      event.stopPropagation();
      if (!confirm('이 세션을 삭제하시겠습니까?')) return;

      try {
        await deleteSession(session.id);
        sessionItem.remove();
      } catch (error) {
        alert(`세션 삭제 실패: ${error.message}`);
      }
    });
    sessionItem.appendChild(deleteBtn);

    sessionItem.addEventListener('click', () => {
      container.querySelectorAll('.session-item, .history-item').forEach((item) => {
        item.classList.remove('active');
      });

      sessionItem.classList.add('active');
      setCurrentSession(session.id);

      if (onSelectSession) {
        onSelectSession(session);
      }
    });

    container.appendChild(sessionItem);
  });
}

export function setupMenuHandlers(handlers) {
  const newChatBtn = document.querySelector('[data-action="new-chat"]');
  const adminBtn = document.querySelector('[data-action="admin"]');
  const logoutBtn = document.querySelector('[data-action="logout"]');

  if (newChatBtn && handlers.newChat && !newChatBtn.dataset.phase2Bound) {
    newChatBtn.dataset.phase2Bound = 'true';
    newChatBtn.addEventListener('click', handlers.newChat);
  }

  if (adminBtn && handlers.admin && !adminBtn.dataset.phase2Bound) {
    adminBtn.dataset.phase2Bound = 'true';
    adminBtn.addEventListener('click', handlers.admin);
  }

  if (logoutBtn && handlers.logout && !logoutBtn.dataset.phase2Bound) {
    logoutBtn.dataset.phase2Bound = 'true';
    logoutBtn.addEventListener('click', handlers.logout);
  }
}

export function setActiveMenu(menuId) {
  document.querySelectorAll('[data-menu-id]').forEach((item) => {
    item.classList.remove('active');
  });

  const activeItem = document.querySelector(`[data-menu-id="${menuId}"]`);
  if (activeItem) {
    activeItem.classList.add('active');
  }
}
