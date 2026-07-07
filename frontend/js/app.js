import { getToken, getUser, removeToken, removeUser, setUser } from './storage.js';
import { isAuthenticated } from './modules/auth.js';
import { MODEL_SELECTION_SOURCES, resolveSelectedModelForAuthenticatedRoute } from './modules/model-selection.js';
import { toast } from './modules/ui.js';
import { apiFetch } from './utils.js';
import { STORAGE_KEYS } from './config.js';
import { initLoginCanvas, initLoginPage } from './pages/login.js?v=20260602_model_sync_fix1';
import { abortActiveChat, initChatPage, resetChatState } from './pages/chat.js?v=20260707_claim_generation_default';
import { initAdminPage } from './pages/admin.js?v=20260707_active_rules_session_defaults';

const PAGES = {
  LOGIN: '/html/login.html',
  CHAT: '/html/chat.html?v=20260707_claim_generation_default',
  ADMIN: '/html/admin.html?v=20260707_active_rules_session_defaults',
};

const ROUTES = {
  LOGIN: '/login',
  CHAT: '/chat',
  ADMIN: '/admin',
};

let me = null;
let componentTemplates = '';

async function loadComponentTemplates() {
  if (componentTemplates) return componentTemplates;
  const response = await fetch('/html/components.html');
  if (!response.ok) throw new Error(`Failed to load components: ${response.status}`);
  componentTemplates = await response.text();
  return componentTemplates;
}

async function loadPageHTML(filePath, activePageId) {
  const response = await fetch(filePath);
  if (!response.ok) {
    throw new Error(`Failed to load page: ${response.status}`);
  }

  const html = await response.text();
  const appContainer = document.getElementById('app');
  if (!appContainer) {
    throw new Error('App container not found');
  }

  appContainer.innerHTML = `${await loadComponentTemplates()}${html}<div id="toast"></div>`;
  if (activePageId) {
    document.getElementById(activePageId)?.classList.add('active');
  }
  return html;
}

function parseRoute(path) {
  const cleanPath = path.split('?')[0].replace(/\/$/, '') || ROUTES.LOGIN;
  if (cleanPath === ROUTES.ADMIN) return 'admin';
  if (cleanPath === ROUTES.CHAT || cleanPath === '/') return 'chat';
  return 'login';
}

async function resolveCurrentUser() {
  try {
    const response = await apiFetch('/auth/me');
    const user = await response.json();
    setUser(user);
    me = normalizeUser(user);
    return me;
  } catch {
    removeUser();
    removeToken();
    me = null;
    return null;
  }
}

function normalizeUser(user) {
  return {
    id: user.id || user.username,
    role: user.role,
    name: user.display_name || user.name || user.username || user.id,
  };
}

async function loadLoginPage() {
  try {
    await loadPageHTML(PAGES.LOGIN, 'page-login');
    initLoginPage({
      onLogin: (username, password) => doLogin(username, password),
    });
    initLoginCanvas();
  } catch (error) {
    console.error('Failed to load login page:', error);
    showErrorAndReload('로그인 페이지 로드 실패');
  }
}

async function loadChatPage() {
  try {
    await loadPageHTML(PAGES.CHAT, 'page-chat');
    await initChatPage({
      currentUser: me,
      onGoAdmin: () => {
        if (me?.role === 'admin') {
          hardNavigateToRoute(ROUTES.ADMIN);
        } else {
          toast('관리자 권한이 없습니다', 'error');
        }
      },
      onLogout: () => doLogout(),
    });
  } catch (error) {
    console.error('Failed to load chat page:', error);
    showErrorAndReload('채팅 페이지 로드 실패');
  }
}

async function loadAdminPage() {
  try {
    if (me?.role !== 'admin') {
      toast('관리자 권한이 없습니다', 'error');
      navigateToRoute(ROUTES.CHAT);
      return;
    }

    await loadPageHTML(PAGES.ADMIN, 'page-admin');
    await initAdminPage({
      isUserAdmin: () => me?.role === 'admin',
      onLogout: () => doLogout(),
      onGoChat: () => hardNavigateToRoute(ROUTES.CHAT),
    });
  } catch (error) {
    console.error('Failed to load admin page:', error);
    showErrorAndReload('관리자 페이지 로드 실패');
  }
}

async function doLogin(username, password) {
  const id = username || document.getElementById('lid')?.value.trim();
  const loginPassword = password || document.getElementById('lpw')?.value;

  try {
    const response = await apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: id, password: loginPassword }),
    });
    const data = await response.json();
    if (data.user) {
      setUser(data.user);
      me = normalizeUser(data.user);
    }
    navigateToRoute(ROUTES.CHAT);
  } catch (error) {
    toast(error.message || '아이디 또는 비밀번호가 올바르지 않습니다.', 'error');
    const passwordInput = document.getElementById('lpw');
    if (passwordInput) {
      passwordInput.value = '';
      passwordInput.focus();
    }
  }
}

async function doLogout() {
  abortActiveChat();
  await apiFetch('/auth/logout', { method: 'POST' }).catch(() => null);
  removeToken();
  removeUser();
  resetChatState();
  me = null;
  navigateToRoute(ROUTES.LOGIN);
}

function navigateToRoute(route) {
  if (window.location.pathname !== route) {
    window.history.pushState({}, '', route);
  }
  loadPageByRoute(parseRoute(route));
}

function hardNavigateToRoute(route) {
  const currentPath = window.location.pathname.replace(/\/$/, '') || '/';
  if (currentPath === route) {
    navigateToRoute(route);
    return;
  }
  window.location.assign(route);
}

async function loadPageByRoute(routeName) {
  cleanupPreviousPage();

  if (routeName !== 'login' && !me) {
    await resolveCurrentUser();
  }

  if (routeName !== 'login' && !me && !isAuthenticated() && !getToken()) {
    navigateToRoute(ROUTES.LOGIN);
    return;
  }

  if (routeName !== 'login' && me) {
    await syncSelectedModelForAuthenticatedRoute();
  }

  switch (routeName) {
    case 'admin':
      await loadAdminPage();
      break;
    case 'chat':
      await loadChatPage();
      break;
    case 'login':
    default:
      await loadLoginPage();
      break;
  }
}

function cleanupPreviousPage() {
  abortActiveChat();
}

async function syncSelectedModelForAuthenticatedRoute() {
  const source = localStorage.getItem(STORAGE_KEYS.SELECTED_LLM_MODEL_SOURCE);
  const selected = localStorage.getItem(STORAGE_KEYS.SELECTED_LLM_MODEL);

  try {
    const response = await apiFetch('/system/models');
    const payload = await response.json();
    const localModels = Array.isArray(payload.providers?.local) ? payload.providers.local : [];
    const localIds = localModels.map((model) => model.id).filter(Boolean);
    const resolved = resolveSelectedModelForAuthenticatedRoute({
      selectedModel: selected,
      source,
      availableLocalIds: localIds,
      defaultLocal: payload.defaults?.local || '',
    });

    if (resolved.model === selected && resolved.source === source) return;

    if (resolved.model) {
      localStorage.setItem(STORAGE_KEYS.SELECTED_LLM_MODEL, resolved.model);
    }
    if (resolved.source) {
      localStorage.setItem(STORAGE_KEYS.SELECTED_LLM_MODEL_SOURCE, resolved.source);
    }
  } catch (error) {
    console.warn('Failed to sync selected model for authenticated route:', error);
  }
}

function showErrorAndReload(message) {
  console.error(message);
  toast(message, 'error');
  if (window.location.pathname !== ROUTES.LOGIN) {
    navigateToRoute(ROUTES.LOGIN);
  }
}

async function initializeApp() {
  try {
    const routeName = parseRoute(window.location.pathname);
    const user = routeName === 'login' ? null : await resolveCurrentUser();

    if (!user && routeName !== 'login') {
      navigateToRoute(ROUTES.LOGIN);
      return;
    }

    await loadPageByRoute(routeName);
  } catch (error) {
    console.error('Failed to initialize app:', error);
    showErrorAndReload('애플리케이션 초기화 실패');
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('popstate', () => {
    loadPageByRoute(parseRoute(window.location.pathname));
  });

  initializeApp();
}
