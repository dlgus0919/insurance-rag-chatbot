import { SESSION_KEYS, STORAGE_KEYS } from '../config.js';
import { createConfirmModal } from '../modules/modal.js';
import { compactClaimBasisItems } from '../modules/claim-result.js';
import { getCurrentSessionId, setCurrentSession } from '../modules/session.js';
import { setupMenuHandlers } from '../modules/sidebar.js';
import { toast } from '../modules/ui.js';
import { apiFetch, escapeHTML, formatSource, readSse } from '../utils.js';

const FALLBACK_LOGO_SRC = '';
const EMBEDDED_REVIEW_TEMPLATE_MARKERS = ['■ 섹션 1', '섹션 1️⃣', '【확정 근거】'];
const EMBEDDED_REVIEW_SECTION_PATTERN = /^\s*■\s*섹션\s*\d/;
const EMBEDDED_REVIEW_HEADING_PATTERN = /^\s*【[^】]+】\s*$/;
const EMBEDDED_REVIEW_BULLET_PATTERN = /^\s*(?:[-*•]\s+|☐\s*|→\s*\d+\.\s*|→\s*)/;
const SOURCE_CITATION_LINE_PATTERN = /^\s*\[출처:\s*.+\]\s*$/;

let me = null;
let msgs = [];
let currentMode = 'general';
let currentSession = null;
let activeAbort = null;

export async function initChatPage({ currentUser, onGoAdmin, onLogout } = {}) {
  me = currentUser || null;

  applyUserToChatPage();
  applySelectedModelLabel();
  renderWelcome();
  showFreshChatNoticeIfNeeded();
  setupChatMenuHandlers({ onGoAdmin, onLogout });
  setupChatInput();
  setupChatDelegatedHandlers();
  setupSettingsHandlers();
  setupDocumentScopeHandlers();
  syncCurrentSessionFromActiveHistory();

  await loadDocumentScopeOptions();
  await loadSessions();
}

export function abortActiveChat() {
  if (activeAbort) {
    activeAbort.abort();
    activeAbort = null;
  }
}

export function resetChatState() {
  abortActiveChat();
  me = null;
  msgs = [];
  currentMode = 'general';
  currentSession = null;
  setCurrentSession(null);
}

function setupChatMenuHandlers({ onGoAdmin, onLogout }) {
  setupMenuHandlers({
    newChat,
    admin: onGoAdmin,
    logout: () => {
      if (!onLogout) return;

      createConfirmModal(
        '로그아웃',
        '정말 로그아웃하시겠습니까?',
        onLogout,
        null
      ).show();
    },
  });
}

function setupChatInput() {
  const chatInput = document.getElementById('chat-input');
  const sendButton = document.querySelector('[data-action="send-message"]') || document.querySelector('.send-btn');

  if (!chatInput || !sendButton) return;

  if (!sendButton.dataset.phase2Bound) {
    sendButton.dataset.phase2Bound = 'true';
    sendButton.addEventListener('click', async () => {
      await sendMsg();
    });
  }

  if (!chatInput.dataset.phase2Bound) {
    chatInput.dataset.phase2Bound = 'true';
    chatInput.addEventListener('keypress', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendButton.click();
      }
    });

    chatInput.addEventListener('input', () => {
      sendButton.disabled = !chatInput.value.trim();
      autoH(chatInput);
    });
  }
}

function setupChatDelegatedHandlers() {
  const page = document.getElementById('page-chat');
  if (!page || page.dataset.phase3Delegated) return;

  page.dataset.phase3Delegated = 'true';
  page.addEventListener('click', async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const suggestion = target.closest('[data-suggestion]');
    if (suggestion) {
      fillSug(suggestion.dataset.suggestion);
      return;
    }

    const historyDelete = target.closest('.hist-del-btn');
    if (historyDelete) {
      await deleteHist(event, historyDelete);
      return;
    }

    const historyItem = target.closest('.history-item[data-session-id]');
    if (historyItem) {
      await loadHist(historyItem, historyItem.dataset.sessionId);
      return;
    }

    const exportItem = target.closest('[data-export-format]');
    if (exportItem) {
      await exportChat(exportItem.dataset.exportFormat);
      return;
    }

    const modeTab = target.closest('[data-mode]');
    if (modeTab) {
      setMode(modeTab.dataset.mode, modeTab);
      return;
    }

    const candidateBtn = target.closest('.candidate-btn');
    if (candidateBtn) {
      const code = candidateBtn.dataset.code || '';
      const name = candidateBtn.dataset.name || '';

      // 입력 폼에 정확한 이름과 코드 세팅
      const rows = [...document.querySelectorAll('[data-claim-line]')];
      // 이름이 일치하거나, 일치하는 게 없으면 첫 번째 줄 선택
      const targetRow = rows.find(r => r.querySelector('.claim-item-name')?.value.trim() === name) || rows[0];

      if (targetRow) {
        const nameInput = targetRow.querySelector('.claim-item-name');
        const codeInput = targetRow.querySelector('.claim-item-code');
        if (nameInput) nameInput.value = name;
        if (codeInput) codeInput.value = code;
      }

      // 자동 재계산 트리거
      await sendClaim({ suppressUserMessage: true, saveToHistory: true });
      return;
    }

    const actionTarget = target.closest('[data-action]');
    const action = actionTarget?.dataset.action;

    if (action === 'toggle-export') {
      toggleExport(event);
    } else if (action === 'toggle-adaptive-k-settings') {
      toggleAdaptiveKSettings(event);
    } else if (action === 'send-claim') {
      await sendClaim();
    } else if (action === 'add-claim-line') {
      addClaimLine();
    } else if (action === 'remove-claim-line') {
      removeClaimLine(actionTarget);
    } else if (action === 'remove-tag') {
      actionTarget.closest('.tag-chip')?.remove();
    }

    if (target.closest('[data-toggle-active="true"]')) {
      target.closest('[data-toggle-active="true"]').classList.toggle('active');
    }
  });
}

function setupSettingsHandlers() {
  document.querySelectorAll('[data-range-format]').forEach((input) => {
    if (input.dataset.phase3Bound) return;
    input.dataset.phase3Bound = 'true';
    input.addEventListener('input', () => {
      const valueEl = input.nextElementSibling;
      if (!valueEl) return;
      valueEl.textContent = input.dataset.rangeFormat === 'decimal'
        ? (Number(input.value) / 10).toFixed(1)
        : input.value;
    });
  });
  const autoParamToggle = document.getElementById('auto-param-toggle');
  if (autoParamToggle && !autoParamToggle.dataset.autoParamBound) {
    autoParamToggle.dataset.autoParamBound = 'true';
    autoParamToggle.checked = isAutoParamsEnabled();
    autoParamToggle.addEventListener('change', () => {
      localStorage.setItem(
        STORAGE_KEYS.AUTO_RAG_PARAMS,
        autoParamToggle.checked ? 'on' : 'off'
      );
      syncAutoParamControls();
    });
  }
  syncAutoParamControls();

  const page = document.getElementById('page-chat');
  if (page && !page.dataset.exportCloseBound) {
    page.dataset.exportCloseBound = 'true';
    page.addEventListener('click', (event) => {
      if (event.target.closest('.export-wrap')) return;
      if (event.target.closest('.adaptive-k-wrap')) return;
      if (event.target.closest('.doc-scope')) return;
      document.getElementById('exp-menu')?.classList.remove('open');
      document.getElementById('adaptive-k-wrap')?.classList.remove('open');
    });
  }

  const reasoningToggle = document.getElementById('reasoning-mode-toggle');
  if (reasoningToggle && !reasoningToggle.dataset.reasoningBound) {
    reasoningToggle.dataset.reasoningBound = 'true';
    reasoningToggle.addEventListener('change', () => {
      localStorage.setItem(
        STORAGE_KEYS.QWEN_REASONING_MODE,
        reasoningToggle.checked ? 'on' : 'off'
      );
    });
  }
  updateReasoningToggleVisibility();
}

function setupDocumentScopeHandlers() {
  const scope = document.getElementById('doc-scope');
  if (!scope || scope.dataset.scopeBound) return;
  scope.dataset.scopeBound = 'true';
  scope.addEventListener('change', (event) => {
    const input = event.target;
    if (!input?.matches?.('[data-doc-scope]')) return;

    const all = scope.querySelector('[data-doc-scope][value="__all__"]');
    if (input.value === '__all__' && input.checked) {
      scope.querySelectorAll('[data-doc-scope]').forEach((item) => {
        if (item !== input) item.checked = false;
      });
    } else if (input.checked && all) {
      all.checked = false;
    }
    if (!selectedDocScopeInputs().length && all) all.checked = true;
    updateDocScopeSummary();
  });
}

async function loadDocumentScopeOptions() {
  try {
    const response = await apiFetch('/chat/documents');
    const data = await response.json();
    renderDocumentScopeOptions(data.documents || []);
  } catch {
    updateDocScopeSummary();
  }
}

function renderDocumentScopeOptions(documents) {
  const list = document.getElementById('doc-scope-options');
  if (!list) return;
  const options = (Array.isArray(documents) ? documents : [])
    .filter((doc) => doc?.doc_short)
    .map((doc) => {
      const name = doc.doc_name && doc.doc_name !== doc.doc_short
        ? `<small>${escapeHTML(doc.doc_name)}</small>`
        : '';
      return `<label class="scope-check"><input type="checkbox" data-doc-scope value="${escapeHTML(doc.doc_short)}"><span>${escapeHTML(doc.doc_short)}${name}</span></label>`;
    });
  if (options.length) list.innerHTML = options.join('');
  updateDocScopeSummary();
}

function selectedDocScopeInputs() {
  return [...document.querySelectorAll('[data-doc-scope]:checked')]
    .filter((input) => input.value !== '__all__');
}

function updateDocScopeSummary() {
  const summary = document.getElementById('doc-scope-summary');
  if (!summary) return;
  const selected = selectedDocScopeInputs();
  summary.textContent = selected.length
    ? `${selected.length}개 선택`
    : '전체';
}

function syncCurrentSessionFromActiveHistory() {
  const activeItem = document.querySelector('.history-item.active[data-session-id]');
  if (activeItem) {
    currentSession = activeItem.dataset.sessionId;
    setCurrentSession(currentSession);
  } else {
    currentSession = getCurrentSessionId();
  }

  return currentSession;
}

function applyUserToChatPage() {
  if (!me) return;

  const uname = document.getElementById('uname');
  const uav = document.getElementById('uav');
  const urole = document.getElementById('urole');
  const adminLink = document.getElementById('admin-link');

  if (uname) uname.textContent = me.name;
  if (uav) uav.textContent = me.name[0] || 'U';
  if (urole) urole.textContent = me.role === 'admin' ? '관리자' : '일반 사용자';
  if (adminLink) {
    adminLink.disabled = me.role !== 'admin';
    if (me.role === 'admin') {
      adminLink.dataset.action = 'admin';
      adminLink.title = '관리자 페이지';
    } else {
      delete adminLink.dataset.action;
      adminLink.removeAttribute('title');
    }
  }
}

function applySelectedModelLabel() {
  const label = document.getElementById('active-model-label');
  if (!label) return;
  label.textContent = formatSelectedModelLabel(getSelectedModel());
  updateReasoningToggleVisibility();
}

function getLogoSrc() {
  return document.querySelector('.sidebar-logo')?.getAttribute('src') || FALLBACK_LOGO_SRC;
}

function getBotLogoSrc() {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="136.925 175 150 150" width="30" height="30"><path d="M286.847 246.661c.053 1.097.084 2.188.091 3.275v.059c0 34.699-23.558 63.896-55.561 72.462a75.75 75.75 0 0 1-16.066 2.465 78.012 78.012 0 0 1-4.879.067c-37.958-.744-69.003-29.684-73.058-66.743a73.03 73.03 0 0 1-.358-4.828 79.557 79.557 0 0 1-.091-3.265v-.158c0-41.412 33.577-74.995 75.005-74.995 35.331 0 64.948 24.421 72.907 57.292a75.139 75.139 0 0 1 2.01 14.369Zm-35.327-34.302c-4.389-1.213-7.634-2.254-8.591-4.27-.453-.954-.176-1.915.449-2.364.677-.494 1.589-.329 2.652.19 1.571.76 3.494 1.89 4.97 2.072 4.301.519 3.515-6.059-4.213-9.877-4.546-2.258-8.994-3.184-15.02-2.96-2.231.092-4.336.011-6.202-.284-2.817-.434-6.269-1.63-8.594-2.114-1.779-.375-2.793-.326-3.217.267-.393.561-.267 1.388.817 2.759 2.175 2.742 5.602 5.792 3.848 12.928-4.339 17.689 1.603 25.785 7.658 27.114 3.392.753 6.518-.042 8.426-2.023 1.813-1.897 2.596-5.106.849-7.823-2.673-4.162-3.617-7.78-1.228-9.285 2.182-1.378 5.283-.108 7.64 5.165 3.771 8.45 8.679 10.691 13.586 4.681 4.02-4.923 3.862-12.051-3.83-14.176Zm-13.657 46.171c-20.342-12.188-30.43-17.009-38.663-22.886-13.642-9.726-15.8-16.974-16.217-22.016-.744-9.025 6.086-17.149 13.039-20.978.536-.326 1.456-1.076 1.056-2.103-.404-1.038-1.649-.838-2.116-.737-15.55 3.3-30.662 16.992-28.315 35.27.937 7.24 5.542 19.467 29.392 33.509 8.135 4.786 15.158 8.415 26.183 14.727 14.929 8.534 21.801 19.531 12.555 31.526-.702.838-1.305 1.707-1.053 2.465.284.876 1.438 1.027 2.515.543 7.097-3.268 12.958-8.173 15.751-12.721 4.914-8.008 7.363-23.714-14.127-36.599Zm-23.793 48.668c-1.803-.519-4.539-1.368-6.82-2.363-2.876-1.256-5.475-2.634-6.622-3.77-.751-.754-.867-1.606-.267-2.482 3.438-4.94 4.406-6.897 5.367-9.222 2.042-4.923.025-5.4-3.143-4.489-3.445.987-6.17 1.993-8.282 2.785-2.961 1.105-4.792 1.782-5.869 1.256-1.122-.544-1.329-2.493-1.733-5.727-.284-2.3-.768-4.923-1.385-7.483-1.274-5.129-3.469-4.144-5.283-2.047-2.259 2.742-3.504 6.136-4.441 7.917-.502.954-1.077 1.269-1.778 1.118-1.565-.333-3.631-2.755-5.887-5.634-3.294-4.211-4.763-7.447-6.479-7.647-3.644-.425-2.024 8.194 1.396 15.298 3.336 6.954 8.511 13.798 17.178 19.275 9.889 6.258 24.503 8.53 33.479 7.268 2.835-.4 3.396-3.24.569-4.053Z" fill="#0046FF" fill-rule="nonzero"/></svg>`;

  if (typeof window !== 'undefined' && typeof window.btoa === 'function') {
    try {
      return 'data:image/svg+xml;base64,' + window.btoa(unescape(encodeURIComponent(svg)));
    } catch (e) {
      console.error('Failed to encode logo to base64', e);
    }
  }
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
}

function renderWelcome() {
  const container = document.getElementById('chat-msgs');
  if (!container) return;
  container.innerHTML = `
      <div class="chat-welcome">
      <div class="welcome-icon">
        <img src="${getLogoSrc()}" alt="신한EZ">
      </div>
      <div class="welcome-title">보상지원 AI 챗봇</div>
      <div class="welcome-sub">약관 분석, 보상 판정, 퀵코드 검색을 도와드립니다.<br>질문을 입력하거나 예시를 선택해 주세요.</div>
      <div class="suggestion-chips">
        <div class="sug-chip" data-suggestion="N39.3 진단코드로 보상 가능 여부 알려주세요">N39.3 보상 가능 여부</div>
        <div class="sug-chip" data-suggestion="실손 3세대와 4세대 약관 차이를 설명해주세요">실손 세대별 약관 비교</div>
        <div class="sug-chip" data-suggestion="3대비급여 보상 기준을 알려주세요">3대비급여 보상 기준</div>
        <div class="sug-chip" data-suggestion="백내장 수술 실손 보상 가능한가요?">백내장 수술 보상</div>
      </div>
    </div>`;
}

async function loadSessions() {
  const list = document.getElementById('hist-list');
  if (!list) return;

  try {
    const response = await apiFetch('/sessions');
    const sessions = await response.json();
    if (currentSession && !sessions.some((session) => session.id === currentSession)) {
      currentSession = null;
      setCurrentSession(null);
    }
    list.innerHTML = sessions.map((session) => `
      <div class="history-item ${session.id === currentSession ? 'active' : ''}" data-session-id="${escapeHTML(session.id)}">
        <div class="h-icon"><svg width="13" height="13" fill="none" viewBox="0 0 24 24"><path d="M21 15a4 4 0 01-4 4H7l-4 4V7a4 4 0 014-4h10a4 4 0 014 4v8z" stroke="currentColor" stroke-width="1.5"/></svg></div>
        <div class="h-title">${escapeHTML(session.title)}</div>
        <button class="hist-del-btn" type="button" title="삭제"><svg width="11" height="11" fill="none" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button>
      </div>`).join('');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function newChat() {
  abortActiveChat();
  msgs = [];
  currentSession = null;
  setCurrentSession(null);
  try {
    window.sessionStorage.setItem(SESSION_KEYS.FRESH_CHAT_NOTICE, '1');
  } catch (error) {
    console.warn('Failed to persist fresh-chat notice flag:', error);
  }
  window.location.assign(`/chat?new=${Date.now()}`);
}

async function loadHist(element, sessionId) {
  document.querySelectorAll('.history-item').forEach((item) => item.classList.remove('active'));
  element.classList.add('active');
  msgs = [];
  currentSession = sessionId;
  setCurrentSession(sessionId);
  renderWelcome();

  try {
    const response = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}/messages`);
    const history = await response.json();
    const container = document.getElementById('chat-msgs');
    container.innerHTML = '';
    history.forEach((message) => {
      const uiPayload = message.role === 'assistant'
        ? (extractAssistantUiPayload(message.sources || []) || { legacyStructuredNotice: true })
        : null;
      const visibleSources = filterVisibleSources(message.sources || []);
      appendMsg(
        message.role === 'assistant' ? 'bot' : message.role,
        message.content,
        visibleSources,
        false,
        uiPayload,
      );
    });
    if (!history.length) renderWelcome();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function deleteHist(event, button) {
  event.stopPropagation();
  const item = button.closest('.history-item');
  if (!item) return;

  const sessionId = item.dataset.sessionId;
  try {
    await apiFetch(`/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
  } catch (error) {
    toast(error.message, 'error');
    return;
  }

  if (item.classList.contains('active')) {
    msgs = [];
    currentSession = null;
    setCurrentSession(null);
    renderWelcome();
  }
  item.remove();
}

function appendMsg(role, text, sources, track = true, uiPayload = null) {
  document.querySelector('.chat-welcome')?.remove();
  const container = document.getElementById('chat-msgs');
  if (!container) return;

  const time = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  const isUser = role === 'user';
  const graphResult = role === 'bot' ? (uiPayload?.graphResult || null) : null;
  const messageText = role === 'bot' ? stripAnswerEmoji(sanitizeAssistantAnswer(text, graphResult)) : String(text || '');
  const sourceHtml = renderSourcesHtml(sources);
  const warnings = role === 'bot' ? (uiPayload?.warnings || []) : [];
  const legacyStructuredNotice = role === 'bot' ? Boolean(uiPayload?.legacyStructuredNotice) : false;
  const claimSnapshot = role === 'bot' ? (uiPayload?.claimSnapshot || null) : null;
  const claimSnapshotHtml = claimSnapshot?.result ? renderClaimResultHtml(claimSnapshot.result) : '';
  const botExtras = role === 'bot'
    ? renderCanonicalDecisionHtml(graphResult)
      + renderClarificationHtml(graphResult)
      + renderWarningHtml(warnings)
      + renderLegacyStructuredNoticeHtml(legacyStructuredNotice)
      + renderGraphReviewPathsHtml(graphResult)
      + renderGraphFactsHtml(graphResult)
    : '';
  const bubbleContent = claimSnapshotHtml || `${renderAssistantContent(messageText)}${botExtras}${sourceHtml}`;
  const row = document.createElement('div');
  row.className = `msg-row ${role}`;
  const avatar = isUser
    ? `<div class="msg-av usr">${me ? me.name[0] : 'U'}</div>`
    : `<div class="msg-av bot"><img src="${getBotLogoSrc()}" alt="AI"></div>`;
  row.innerHTML = `${avatar}<div><div class="msg-bubble">${bubbleContent}</div><div class="msg-meta">${time}</div></div>`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  if (track) msgs.push({ role, text: messageText, time, sources: sources || [], graphResult, warnings });
}

function showTyping() {
  document.querySelector('.chat-welcome')?.remove();
  const container = document.getElementById('chat-msgs');
  if (!container) return;

  const row = document.createElement('div');
  row.className = 'msg-row bot';
  row.id = 'typing';
  row.innerHTML = `<div class="msg-av bot"><img src="${getBotLogoSrc()}" alt="AI"></div><div><div class="msg-bubble" style="padding:12px 15px;"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div></div>`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

function removeTyping() {
  document.getElementById('typing')?.remove();
}

function fillSug(text) {
  const input = document.getElementById('chat-input');
  if (!input) return;
  input.value = text;
  sendMsg();
}

async function sendMsg() {
  const input = document.getElementById('chat-input');
  const text = input?.value.trim();
  if (!text) return;

  appendMsg('user', text);
  input.value = '';
  input.style.height = 'auto';
  const mode = currentMode === 'claim' ? 'general' : currentMode;
  await streamChat(text, mode, getActiveScopeFilters());
}

async function sendClaim(options = {}) {
  const { suppressUserMessage = false, saveToHistory = true } = options;
  const items = collectClaimItems();
  if (!items.length) {
    toast('청구 항목을 1개 이상 입력하세요.');
    return;
  }
  const diagnosisCode = document.getElementById('claim-diagnosis-code')?.value.trim() || '';
  const coverageTopic = document.getElementById('claim-coverage-topic')?.value.trim() || '실손';
  const visitType = document.getElementById('claim-visit-type')?.value || '';
  const note = document.getElementById('claim-note')?.value.trim() || '';
  const policyGeneration = document.querySelector('input[name="claim-policy-generation"]:checked')?.value || '5th';
  const specialCalculationStatus = getSpecialCalculationStatus();

  const itemSummary = items.map((item) => {
    const insured = item.insured_copay_amount || '0';
    const nonpay = item.nonpay_amount || '0';
    return `${item.input_name} 급여본인부담 ${insured}원 / 비급여 ${nonpay}원 x ${item.quantity}`;
  }).join(', ');
  if (!suppressUserMessage) {
    appendMsg('user', `[보험금 계산/${policyGeneration === '5th' ? '5세대' : '4세대'}/${specialCalculationLabel(specialCalculationStatus)}] ${itemSummary}`);
  }
  await calculateClaim({
    session_id: currentSession,
    save_to_history: saveToHistory,
    items,
    context: {
      visit_type: visitType,
      coverage_topic: coverageTopic,
      diagnosis_code: diagnosisCode,
      situation_note: note,
      policy_generation: policyGeneration,
      special_calculation_status: specialCalculationStatus,
    },
    model: getSelectedModel(),
    top_k: getTopK(),
    index_mode: getIndexMode(),
  });
}

function collectClaimItems() {
  return [...document.querySelectorAll('[data-claim-line]')]
    .map((row, index) => {
      const inputName = row.querySelector('.claim-item-name')?.value.trim() || '';
      const legacyClaimedAmount = row.querySelector('.claim-amount')?.value.trim() || '';
      const insuredCopayAmount = row.querySelector('.claim-insured-copay-amount')?.value.trim() || '';
      const nonpayAmount = row.querySelector('.claim-nonpay-amount')?.value.trim() || '';
      const totalAmount = sumMoneyInputs(insuredCopayAmount, nonpayAmount) || legacyClaimedAmount;
      if (!inputName || !totalAmount) return null;
      return {
        line_id: `line-${index + 1}`,
        input_name: inputName,
        input_code: row.querySelector('.claim-item-code')?.value.trim() || '',
        claimed_amount: totalAmount,
        insured_copay_amount: insuredCopayAmount,
        nonpay_amount: nonpayAmount,
        quantity: row.querySelector('.claim-quantity')?.value.trim() || '1',
        user_category_hint: row.querySelector('.claim-category-hint')?.value || '',
        extra_info: row.querySelector('.claim-extra-info')?.value.trim() || '',
      };
    })
    .filter(Boolean);
}

function sumMoneyInputs(...values) {
  let hasValue = false;
  let total = 0;
  for (const raw of values) {
    const text = String(raw || '').replace(/[,\s원]/g, '');
    if (!text) continue;
    const numeric = Number(text);
    if (!Number.isFinite(numeric)) return raw;
    hasValue = true;
    total += numeric;
  }
  return hasValue ? String(total) : '';
}

function resetClaimForm() {
  const lines = document.getElementById('claim-lines');
  const rows = lines ? [...lines.querySelectorAll('[data-claim-line]')] : [];
  if (!rows.length) return;

  rows.slice(1).forEach((row) => row.remove());
  const firstRow = rows[0];
  firstRow.querySelectorAll('input').forEach((input) => {
    input.value = input.classList.contains('claim-quantity') ? '1' : '';
  });
  firstRow.querySelectorAll('select').forEach((select) => {
    select.value = '';
  });
  syncClaimLineLabels();

  const generation = document.querySelector('input[name="claim-policy-generation"][value="5th"]');
  if (generation instanceof HTMLInputElement) generation.checked = true;
  const specialStatus = document.querySelector('input[name="claim-special-calculation"][value="unknown"]');
  if (specialStatus instanceof HTMLInputElement) specialStatus.checked = true;

  const diagnosisCode = document.getElementById('claim-diagnosis-code');
  const coverageTopic = document.getElementById('claim-coverage-topic');
  const visitType = document.getElementById('claim-visit-type');
  const note = document.getElementById('claim-note');

  if (diagnosisCode instanceof HTMLInputElement) diagnosisCode.value = '';
  if (coverageTopic instanceof HTMLInputElement) coverageTopic.value = '';
  if (visitType instanceof HTMLSelectElement) visitType.value = '';
  if (note instanceof HTMLTextAreaElement) note.value = '';
}

function showFreshChatNoticeIfNeeded() {
  try {
    if (window.sessionStorage.getItem(SESSION_KEYS.FRESH_CHAT_NOTICE) !== '1') return;
    window.sessionStorage.removeItem(SESSION_KEYS.FRESH_CHAT_NOTICE);
    resetClaimForm();
    toast('새 채팅이 시작되었습니다.');
  } catch (error) {
    console.warn('Failed to restore fresh-chat notice flag:', error);
  }
}

function addClaimLine() {
  const lines = document.getElementById('claim-lines');
  const first = lines?.querySelector('[data-claim-line]');
  if (!lines || !first) return;

  const next = first.cloneNode(true);
  next.querySelectorAll('input').forEach((input) => {
    input.value = input.classList.contains('claim-quantity') ? '1' : '';
  });
  next.querySelectorAll('select').forEach((select) => {
    select.value = '';
  });
  lines.appendChild(next);
  syncClaimLineLabels();
}

function removeClaimLine(button) {
  const lines = document.getElementById('claim-lines');
  const rows = lines ? [...lines.querySelectorAll('[data-claim-line]')] : [];
  if (rows.length <= 1) {
    rows[0]?.querySelectorAll('input').forEach((input) => {
      input.value = input.classList.contains('claim-quantity') ? '1' : '';
    });
    rows[0]?.querySelectorAll('select').forEach((select) => {
      select.value = '';
    });
    return;
  }
  button.closest('[data-claim-line]')?.remove();
  syncClaimLineLabels();
}

function syncClaimLineLabels() {
  document.querySelectorAll('[data-claim-line]').forEach((row, index) => {
    row.classList.toggle('is-extra', index > 0);
  });
}

async function calculateClaim(payload) {
  abortActiveChat();
  activeAbort = new AbortController();
  showTyping();
  try {
    const response = await apiFetch('/claim/calculate', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal: activeAbort.signal,
    });
    const result = await response.json();
    removeTyping();
    if (result.session_id) {
      currentSession = result.session_id;
      setCurrentSession(currentSession);
    }
    appendClaimResult(result);
    if (result.session_id) await loadSessions();
  } catch (error) {
    removeTyping();
    if (error.name !== 'AbortError') appendMsg('bot', '오류: ' + error.message, []);
  } finally {
    activeAbort = null;
  }
}

async function streamChat(query, mode = 'general', filters = {}, memo = '') {
  abortActiveChat();
  activeAbort = new AbortController();
  const chatInput = document.getElementById('chat-input');
  const sendButton = document.querySelector('.send-btn');
  if (chatInput) chatInput.disabled = true;
  if (sendButton) sendButton.disabled = true;
  showTyping();

  let botRow = null;
  let bubble = null;
  let answer = '';
  let sources = [];
  let graphResult = null;
  let warnings = [];

  try {
    const payload = {
      query,
      session_id: currentSession,
      mode,
      model: getSelectedModel(),
      reasoning_mode: getReasoningMode(),
      top_k: getTopK(),
      temperature: getTemperature(),
      auto_params: isAutoParamsEnabled(),
      adaptive_k: isAutoParamsEnabled(),
      filters,
      policy_generation: getPolicyGeneration(),
      index_mode: getIndexMode(),
    };
    if (memo) payload.memo = memo;
    const response = await apiFetch('/chat/stream', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal: activeAbort.signal,
    });

    removeTyping();
    botRow = createBotStreamRow();
    bubble = botRow.querySelector('.msg-bubble');
    await readSse(response.body.getReader(), (event) => {
      if (event.event === 'sources') sources = event.data || [];
      if (event.event === 'graph') graphResult = event.data || null;
      if (event.event === 'warning') warnings.push(event.data || {});
      if (event.event === 'token') {
        answer += event.data.t || '';
        bubble.innerHTML = renderAssistantContent(answer);
      }
      if (event.event === 'final' && event.data.answer) {
        answer = event.data.answer;
        bubble.innerHTML = renderAssistantContent(answer);
      }
      if (event.event === 'done' && event.data.session_id) {
        currentSession = event.data.session_id;
        setCurrentSession(currentSession);
        if (event.data.answer) answer = event.data.answer;
      }
      if (event.event === 'error') throw new Error(event.data.message || '응답 생성 중 오류가 발생했습니다.');
    });
    if (!answer) answer = '응답이 비어 있습니다.';
    answer = sanitizeAssistantAnswer(answer, graphResult);
    bubble.innerHTML = renderAssistantContent(answer)
      + renderCanonicalDecisionHtml(graphResult)
      + renderClarificationHtml(graphResult)
      + renderWarningHtml(warnings)
      + renderGraphReviewPathsHtml(graphResult)
      + renderGraphFactsHtml(graphResult)
      + renderSourcesHtml(sources);
    msgs.push({
      role: 'bot',
      text: answer,
      time: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
      sources,
      graphResult,
      warnings,
    });
    await loadSessions();
  } catch (error) {
    removeTyping();
    if (error.name !== 'AbortError') appendMsg('bot', '오류: ' + error.message, []);
  } finally {
    activeAbort = null;
    if (chatInput) {
      chatInput.disabled = false;
      chatInput.focus();
    }
    if (sendButton) sendButton.disabled = false;
  }
}

function appendClaimResult(result) {
  document.querySelector('.chat-welcome')?.remove();
  const container = document.getElementById('chat-msgs');
  if (!container) return;

  const row = document.createElement('div');
  row.className = 'msg-row bot';
  const time = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  row.innerHTML = `
    <div class="msg-av bot"><img src="${getBotLogoSrc()}" alt="AI"></div>
    <div>
      <div class="msg-bubble">
        ${renderClaimResultHtml(result)}
      </div>
      <div class="msg-meta">${time}</div>
    </div>`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  msgs.push({
    role: 'bot',
    text: claimResultToText(result),
    time,
    sources: result.applied_basis || [],
  });
}

function claimLineNeedsReview(line) {
  return line?.requires_review === true
    || line?.calculation_status === 'partial_human_task'
    || line?.excluded_from_calculation === true
    || Number(line?.human_task_amount || 0) > 0;
}

function renderClaimResultHtml(result) {
  if (result.candidates?.length) {
    return `
      <div class="claim-result">
        <div class="claim-section">
          <div class="evidence-title">여러 항목이 발견되었습니다. 가장 정확한 것을 선택해 주세요.</div>
          <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;">
            ${result.candidates.slice(0, 6).map((candidate) =>
              `<button type="button" class="tag-chip candidate-btn" style="cursor:pointer;" data-code="${escapeHTML(candidate.code || '')}" data-name="${escapeHTML(candidate.name || '')}">
                 ${escapeHTML(candidate.code || '')} ${escapeHTML(candidate.name || '')}
               </button>`
            ).join('')}
          </div>
        </div>
      </div>`;
  }

  const noteHtml = result.notes ? `<div class="claim-note-alert">${escapeHTML(result.notes)}</div>` : '';
  const reasons = result.review_reasons?.length
    ? `<div class="claim-section"><div class="evidence-title">검토 사유</div><ul>${result.review_reasons.map((reason) => `<li>${escapeHTML(reason)}</li>`).join('')}</ul></div>`
    : '';
  const warnings = result.warnings?.length
    ? `<div class="claim-section claim-warning"><div class="evidence-title">처리 경고</div><ul>${result.warnings.map((warning) => `<li>${escapeHTML(warning)}</li>`).join('')}</ul></div>`
    : '';
  const candidates = ''; // candidates handled above
  const compactBasisItems = compactClaimBasisItems(result.applied_basis, 4);
  const basis = compactBasisItems.length
    ? `<details class="claim-section claim-basis-details"><summary class="evidence-title">적용 근거 보기</summary><ul>${compactBasisItems.map((basisItem) => {
        const extra = basisItem.extraCount > 0
          ? ` <span class="claim-inline-note">외 ${basisItem.extraCount}건</span>`
          : '';
        const reviewClass = basisItem.reviewStatus === 'review_required' ? ' class="claim-review-basis"' : '';
        return `<li${reviewClass}><strong>${escapeHTML(basisItem.source || '근거')}</strong>${extra}: ${escapeHTML(truncateUiText(basisItem.content || '', 180))}</li>`;
      }).join('')}</ul></details>`
    : '';
  const calculatedLines = (result.line_results || []).filter((line) => line.calculation_status !== 'human_task');
  const humanTaskLines = (result.line_results || []).filter((line) =>
    line.calculation_status === 'human_task' ||
    line.calculation_status === 'partial_human_task' ||
    Number(line.human_task_amount || 0) > 0
  );
  const lineResults = calculatedLines.length
    ? `<div class="claim-section"><div class="evidence-title">항목별 계산</div><ul>${calculatedLines.map((line) => {
        const splitAmount = Number(line.insured_copay_amount || 0) > 0 || Number(line.nonpay_amount || 0) > 0
          ? `급여본인부담 ${formatMoney(line.insured_copay_amount)}원 / 비급여 ${formatMoney(line.nonpay_amount)}원 / `
          : '';
        const reviewClass = claimLineNeedsReview(line) ? ' class="claim-review-line"' : '';
        return `<li${reviewClass}><strong>${escapeHTML(line.input_name || '')}</strong> (${escapeHTML(line.category || '미분류')}): ${splitAmount}청구 ${formatMoney(line.claimed_amount)}원 / 공제 ${formatMoney(line.deductible)}원 / 지급 ${formatMoney(line.payable_amount)}원</li>`;
      }).join('')}</ul></div>`
    : '';
  const humanTaskResults = humanTaskLines.length
    ? `<div class="claim-section claim-warning"><div class="evidence-title">Human Task 분류</div><ul>${humanTaskLines.map((line) => {
        const reasons = Array.isArray(line.review_reasons) && line.review_reasons.length
          ? ` - ${escapeHTML(line.review_reasons[0])}`
          : '';
        const taskAmount = line.human_task_amount || line.claimed_amount;
        const splitAmount = Number(line.insured_copay_amount || 0) > 0 || Number(line.nonpay_amount || 0) > 0
          ? `급여본인부담 ${formatMoney(line.insured_copay_amount)}원 / 비급여 ${formatMoney(line.nonpay_amount)}원 / `
          : '';
        return `<li><strong>${escapeHTML(line.input_name || '')}</strong> (${escapeHTML(line.category || '미분류')}): ${splitAmount}Human Task 금액 ${formatMoney(taskAmount)}원은 자동 지급 산정에서 제외했습니다.${reasons}</li>`;
      }).join('')}</ul></div>`
    : '';

  return `
    <div class="claim-result">
      ${noteHtml}
      <div class="claim-note-text">계산 기준: ${result.policy_generation === '5th' ? '5세대 실손 표준약관' : '4세대 실손 기준'}</div>
      <div class="claim-note-text">산정특례 상태: ${escapeHTML(specialCalculationLabel(result.special_calculation_status || 'unknown'))}</div>
      <div class="claim-summary-grid">
        <div class="claim-summary-claimed"><span>총 청구금액</span><strong>${formatMoney(result.claimed_amount)}원</strong></div>
        <div class="claim-summary-deductible"><span>예상 공제금액</span><strong>${formatMoney(result.deductible)}원</strong></div>
        <div class="claim-summary-payable"><span>예상 지급금액</span><strong>${formatMoney(result.payable_amount)}원</strong></div>
      </div>
      ${lineResults}
      ${humanTaskResults}
      ${warnings}
      ${reasons}
      ${candidates}
      ${basis}
    </div>`;
}

function claimResultToText(result) {
  if (result.candidates?.length) {
    return '여러 항목이 발견되었습니다. 가장 정확한 것을 선택해 주세요.';
  }
  const lines = [
    `보험금 계산 결과: ${result.requires_review ? '검토 필요' : '계산 완료'}`,
    `계산 기준: ${result.policy_generation === '5th' ? '5세대 실손 표준약관' : '4세대 실손 기준'}`,
    `산정특례 상태: ${specialCalculationLabel(result.special_calculation_status || 'unknown')}`,
    `총 청구금액: ${formatMoney(result.claimed_amount)}원`,
    `예상 공제금액: ${formatMoney(result.deductible)}원`,
    `예상 지급금액: ${formatMoney(result.payable_amount)}원`,
  ];
  if (result.review_reasons?.length) {
    lines.push(`검토 사유: ${result.review_reasons.join(' / ')}`);
  }
  const humanTaskLines = (result.line_results || []).filter((line) =>
    line.calculation_status === 'human_task' ||
    line.calculation_status === 'partial_human_task' ||
    Number(line.human_task_amount || 0) > 0
  );
  if (humanTaskLines.length) {
    lines.push(`Human Task 분류: ${humanTaskLines.map((line) => `${line.input_name || ''} ${formatMoney(line.human_task_amount || line.claimed_amount)}원`).join(' / ')}`);
  }
  return lines.join('\n');
}

function truncateUiText(text, maxLength = 240) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function formatMoney(value) {
  const numeric = Number(String(value || '0').replace(/,/g, ''));
  if (!Number.isFinite(numeric)) return escapeHTML(value || '0');
  return numeric.toLocaleString('ko-KR');
}

function renderClarificationHtml(graphResult) {
  const plan = graphResult?.plan || {};
  const questions = Array.isArray(plan.clarification_questions) ? plan.clarification_questions : [];
  const terms = plan.normalized_terms && typeof plan.normalized_terms === 'object' ? plan.normalized_terms : {};
  const candidates = Array.isArray(plan.term_correction_candidates) ? plan.term_correction_candidates : [];
  const ambiguous = Array.isArray(plan.ambiguous_terms) ? plan.ambiguous_terms : [];
  const requiredEvidence = [...new Set([
    ...(Array.isArray(plan.required_evidence) ? plan.required_evidence : []),
    ...(Array.isArray(graphResult?.required_evidence) ? graphResult.required_evidence : []),
  ].map((value) => String(value || '').trim()).filter(Boolean))];
  if (!questions.length && !Object.keys(terms).length && !candidates.length && !ambiguous.length && !requiredEvidence.length) return '';

  const questionHtml = questions.length
    ? `<div class="clarify-subtitle">추가 확인 질문</div><ul>${questions.map((question) => `<li>${escapeHTML(question)}</li>`).join('')}</ul>`
    : '';
  const termHtml = Object.keys(terms).length
    ? `<div class="clarify-subtitle">입력 용어 정규화</div><ul>${Object.entries(terms).map(([raw, normalized]) => `<li>${escapeHTML(raw)} → ${escapeHTML(normalized)}</li>`).join('')}</ul>`
    : '';
  const candidateHtml = candidates.length
    ? `<div class="clarify-subtitle">입력 용어 보정 후보</div><ul>${candidates.map((item) => `<li>${escapeHTML(item.raw || '')} → ${escapeHTML(item.normalized || '')} <span class="muted">(확인 필요)</span></li>`).join('')}</ul>`
    : '';
  const ambiguousHtml = ambiguous.length
    ? `<div class="clarify-tags">${ambiguous.map((term) => `<span>${escapeHTML(term)}</span>`).join('')}</div>`
    : '';
  const evidenceHtml = requiredEvidence.length
    ? `<div class="clarify-subtitle">확인할 자료</div><ul>${requiredEvidence.map((item) => `<li>${escapeHTML(item)}</li>`).join('')}</ul>`
    : '';

  return `<div class="msg-clarifications"><div class="evidence-title">추가 확인 필요</div>${ambiguousHtml}${questionHtml}${evidenceHtml}${termHtml}${candidateHtml}</div>`;
}

function renderCanonicalDecisionHtml(graphResult) {
  const decision = graphResult?.canonical_decision;
  if (!decision || typeof decision !== 'object') return '';

  const status = String(decision.status_label || '약관 조항 확인').trim();
  const summary = String(decision.summary || '').trim();
  const authority = String(decision.authority_note || '').trim();
  const conditions = Array.isArray(decision.conditions)
    ? decision.conditions.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  const evidence = Array.isArray(decision.source_evidence) ? decision.source_evidence : [];
  if (!status && !summary && !authority && !conditions.length && !evidence.length) return '';

  const conditionsHtml = conditions.length
    ? `<div class="review-line"><strong>적용 조건</strong>: ${conditions.map(escapeHTML).join(', ')}</div>`
    : '';
  const sourceText = evidence.map((source) => {
    const documentName = String(source?.doc_short || '약관').trim();
    const pageStart = source?.page_start;
    const pageEnd = source?.page_end;
    if (pageStart === null || pageStart === undefined || pageStart === '') return documentName;
    return pageEnd && pageEnd !== pageStart
      ? `${documentName} p.${pageStart}-${pageEnd}`
      : `${documentName} p.${pageStart}`;
  }).filter(Boolean);
  const sourceHtml = sourceText.length
    ? `<div class="review-line"><strong>직접 조항 근거</strong>: ${sourceText.map(escapeHTML).join(', ')}</div>`
    : '';
  const summaryHtml = summary ? `<div class="review-summary">${escapeHTML(summary)}</div>` : '';
  const authorityHtml = authority ? `<div class="review-line">${escapeHTML(authority)}</div>` : '';

  return `<div class="graph-review-paths canonical-decision"><div class="evidence-title">${escapeHTML(status)}</div>${summaryHtml}${authorityHtml}${conditionsHtml}${sourceHtml}</div>`;
}

function renderWarningHtml(warnings) {
  if (!warnings?.length) return '';
  const items = warnings
    .map((warning) => `<li>${escapeHTML(warning.message || warning.code || '처리 중 경고가 발생했습니다.')}</li>`)
    .join('');
  return `<div class="msg-warnings"><div class="evidence-title">처리 경고</div><ul>${items}</ul></div>`;
}

function hasRenderableGraphPayload(graphResult) {
  if (!graphResult || typeof graphResult !== 'object') return false;
  if (graphResult.canonical_decision && typeof graphResult.canonical_decision === 'object') return true;
  if (Array.isArray(graphResult.graph_review_paths) && graphResult.graph_review_paths.length > 0) return true;
  if (Array.isArray(graphResult.facts) && graphResult.facts.length > 0) return true;

  const plan = graphResult.plan && typeof graphResult.plan === 'object' ? graphResult.plan : {};
  return Boolean(
    (Array.isArray(plan.clarification_questions) && plan.clarification_questions.length > 0)
    || (Array.isArray(plan.required_evidence) && plan.required_evidence.length > 0)
    || (plan.normalized_terms && typeof plan.normalized_terms === 'object' && Object.keys(plan.normalized_terms).length > 0)
    || (Array.isArray(plan.term_correction_candidates) && plan.term_correction_candidates.length > 0)
    || (Array.isArray(plan.ambiguous_terms) && plan.ambiguous_terms.length > 0)
  );
}

function sanitizeAssistantAnswer(answer, graphResult = null) {
  const text = String(answer || '').trim();
  if (!text) return '';
  if (!hasRenderableGraphPayload(graphResult)) return stripTrailingSourceCitationLines(text);

  const positions = EMBEDDED_REVIEW_TEMPLATE_MARKERS
    .map((marker) => text.indexOf(marker))
    .filter((index) => index >= 0);
  if (!positions.length) return stripTrailingSourceCitationLines(text);

  const cutIndex = Math.min(...positions);
  const leading = text.slice(0, cutIndex).trimEnd();
  if (leading) return stripTrailingSourceCitationLines(leading);

  const answerMarker = text.indexOf('[답변]');
  if (answerMarker >= 0) {
    const extracted = text.slice(answerMarker + '[답변]'.length).trim();
    if (extracted) return stripTrailingSourceCitationLines(extracted);
  }
  return stripTrailingSourceCitationLines(summarizeEmbeddedReviewTemplate(text));
}

function summarizeEmbeddedReviewTemplate(text) {
  const candidates = [];
  String(text || '').split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.replace(/\u00a0/g, ' ').trim();
    if (!line) return;
    if (line.startsWith('[출처:')) return;
    if (EMBEDDED_REVIEW_SECTION_PATTERN.test(line)) return;
    if (EMBEDDED_REVIEW_HEADING_PATTERN.test(line)) return;
    if (line === '해당 없음') return;
    if (line.includes('Graph review path')) return;
    if (line.startsWith('⚠️')) return;
    if (line.startsWith('➜')) return;
    if (line.includes('현황:') && line.includes('중요도:')) return;

    const cleaned = line.replace(EMBEDDED_REVIEW_BULLET_PATTERN, '').trim();
    if (!cleaned) return;
    if (!candidates.includes(cleaned)) candidates.push(cleaned);
  });

  if (!candidates.length) return '제공된 구조화 검토 경로 기준으로 추가 확인이 필요합니다.';
  const summary = candidates.slice(0, 3).join(' ').replace(/\s+/g, ' ').trim();
  if (!summary) return '제공된 구조화 검토 경로 기준으로 추가 확인이 필요합니다.';
  return /[.!?]$/.test(summary) ? summary : `${summary}.`;
}

function stripTrailingSourceCitationLines(text) {
  const lines = String(text || '').trim().split(/\r?\n/);
  if (!lines.length) return '';

  let end = lines.length;
  while (end > 0) {
    const line = lines[end - 1].trim();
    if (!line) {
      end -= 1;
      continue;
    }
    if (SOURCE_CITATION_LINE_PATTERN.test(line)) {
      end -= 1;
      continue;
    }
    break;
  }

  const stripped = lines.slice(0, end);
  while (stripped.length && !stripped[stripped.length - 1].trim()) {
    stripped.pop();
  }
  const cleaned = stripped.join('\n').trim();
  return cleaned || String(text || '').trim();
}

function stripAnswerEmoji(text) {
  return String(text || '').replace(/[\p{Extended_Pictographic}\uFE0F\u20E3]/gu, '').replace(/\s{2,}/g, ' ').trim();
}

function renderAssistantContent(text) {
  const normalized = String(text || '').replace(/<br\s*\/?>/gi, '\uE000');
  const lines = normalized.split(/\r?\n/);
  const html = [];

  for (let index = 0; index < lines.length;) {
    if (!lines[index].trim()) {
      html.push('<br>');
      index += 1;
      continue;
    }

    if (isMarkdownTableStart(lines, index)) {
      const { html: tableHtml, nextIndex } = renderMarkdownTable(lines, index);
      html.push(tableHtml);
      index = nextIndex;
      continue;
    }

    const orderedItems = collectList(lines, index, /^\s*\d+\.\s+(.+)$/);
    if (orderedItems) {
      html.push(`<ol>${orderedItems.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('')}</ol>`);
      index = orderedItems.nextIndex;
      continue;
    }

    const unorderedItems = collectList(lines, index, /^\s*[-*]\s+(.+)$/);
    if (unorderedItems) {
      html.push(`<ul>${unorderedItems.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('')}</ul>`);
      index = unorderedItems.nextIndex;
      continue;
    }

    html.push(`<p>${renderInlineMarkdown(lines[index])}</p>`);
    index += 1;
  }

  return html.join('');
}

function isMarkdownTableStart(lines, index) {
  return isPipeRow(lines[index]) && isTableSeparator(lines[index + 1] || '');
}

function isPipeRow(line) {
  const trimmed = line.trim();
  return trimmed.startsWith('|') && trimmed.endsWith('|') && trimmed.includes('|', 1);
}

function isTableSeparator(line) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function splitTableRow(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
}

function renderMarkdownTable(lines, startIndex) {
  const headers = splitTableRow(lines[startIndex]);
  const rows = [];
  let index = startIndex + 2;

  while (index < lines.length && isPipeRow(lines[index])) {
    const cells = splitTableRow(lines[index]);
    rows.push(headers.map((_, cellIndex) => cells[cellIndex] || ''));
    index += 1;
  }

  const head = `<thead><tr>${headers.map((header) => `<th>${renderInlineMarkdown(header)}</th>`).join('')}</tr></thead>`;
  const body = `<tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}</tbody>`;
  return {
    html: `<div class="msg-table-wrap"><table class="msg-table">${head}${body}</table></div>`,
    nextIndex: index,
  };
}

function collectList(lines, startIndex, pattern) {
  const items = [];
  let index = startIndex;
  while (index < lines.length) {
    const match = lines[index].match(pattern);
    if (!match) break;
    items.push(match[1]);
    index += 1;
  }
  return items.length ? { items, nextIndex: index } : null;
}

function renderInlineMarkdown(text) {
  return escapeHTML(text)
    .replace(/\uE000/g, '<br>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}

function renderGraphReviewPathsHtml(graphResult) {
  const paths = Array.isArray(graphResult?.graph_review_paths) ? graphResult.graph_review_paths : [];
  if (!paths.length) return '';

  const items = paths.slice(0, 4).map((path) => {
    const label = escapeHTML(path.path_type_label || path.path_type || '구조화 검토');
    const status = escapeHTML(path.status_label || path.status || '검토 필요');
    const summary = path.summary ? `<div class="review-summary">${escapeHTML(path.summary)}</div>` : '';
    const evidence = Array.isArray(path.required_evidence) && path.required_evidence.length
      ? `<div class="review-line"><strong>필요 증빙</strong>: ${path.required_evidence.map(escapeHTML).join(', ')}</div>`
      : '';
    const ruleRows = [
      ['적용 가능 면책 사유', path.exclusion_reasons],
      ['적용 한도', path.benefit_limits],
      ['적용 공제', path.deductible_rules],
      ['필요 서류', path.required_documents],
      ['중복 보상 조정', path.coordination_rules],
      ['세대/갱신 기준', path.generation_rules],
    ].map(([title, values]) => Array.isArray(values) && values.length
      ? `<div class="review-line"><strong>${title}</strong>: ${values.map(escapeHTML).join(', ')}</div>`
      : '').join('');
    const actions = Array.isArray(path.review_actions) && path.review_actions.length
      ? `<div class="review-line"><strong>권장 조치</strong>: ${path.review_actions.map(escapeHTML).join(', ')}</div>`
      : '';
    return `<li><div><strong>${label}</strong> <span class="review-status">${status}</span></div>${summary}${ruleRows}${evidence}${actions}</li>`;
  }).join('');

  return `<div class="graph-review-paths"><div class="evidence-title">구조화 검토 경로</div><ul>${items}</ul></div>`;
}

function renderLegacyStructuredNoticeHtml(shouldRender) {
  if (!shouldRender) return '';
  return '<div class="graph-review-paths"><div class="evidence-title">구조화 검토 경로</div><ul><li>(이전 세션 — 구조화 검토 패널 미지원)</li></ul></div>';
}

function renderGraphFactsHtml(graphResult) {
  const facts = graphResult?.facts || [];
  if (!facts.length) return '';

  const byStatus = {
    confirmed: [],
    candidate: [],
    missing: [],
  };
  facts.forEach((fact) => {
    const status = byStatus[fact.status] ? fact.status : 'candidate';
    byStatus[status].push(fact);
  });

  const sections = [
    ['confirmed', '확정 근거'],
    ['candidate', '검토 후보 (확정 아님)'],
    ['missing', '구조화 DB 누락'],
  ].map(([status, label]) => {
    if (!byStatus[status].length) return '';
    const items = byStatus[status]
      .slice(0, 8)
      .map((fact) => `<li>${renderGraphFactLine(fact, status)}</li>`)
      .join('');
    return `<div class="graph-section graph-${status}"><div class="graph-section-title">${label}</div><ul>${items}</ul></div>`;
  }).join('');

  return `<div class="graph-facts"><div class="evidence-title">구조화 근거</div>${sections}</div>`;
}

function renderGraphFactLine(fact, status) {
  const subject = escapeHTML(fact.subject || '');
  const relation = escapeHTML(fact.relation || '');
  const object = escapeHTML(fact.object || 'N/A');
  const evidence = fact.evidence?.[0];
  const page = evidence?.page_start ? ` p.${evidence.page_start}` : '';
  const source = evidence?.doc_short ? ` (${escapeHTML(evidence.doc_short)}${page})` : '';
  const caution = status === 'candidate' ? ' - 검토 후보, 확정 판단 아님' : '';
  return `${subject} --${relation}--> ${object}${source}${caution}`;
}

function createBotStreamRow() {
  const container = document.getElementById('chat-msgs');
  const row = document.createElement('div');
  row.className = 'msg-row bot';
  row.innerHTML = `<div class="msg-av bot"><img src="${getBotLogoSrc()}" alt="AI"></div><div><div class="msg-bubble"></div><div class="msg-meta">${new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}</div></div>`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  return row;
}

function syncModeChrome(mode) {
  document.getElementById('page-chat')?.classList.toggle('claim-mode', mode === 'claim');
}

function setMode(mode, element) {
  syncModeChrome(mode);
  if (mode === currentMode) return;
  currentMode = mode;
  document.querySelectorAll('.mode-tab').forEach((tab) => tab.classList.remove('active'));
  element.classList.add('active');
  document.getElementById('panel-claim')?.classList.remove('visible');
  if (mode === 'claim') document.getElementById('panel-claim')?.classList.add('visible');
  msgs = [];
  renderWelcome();
}

function autoH(element) {
  element.style.height = 'auto';
  element.style.height = Math.min(element.scrollHeight, 120) + 'px';
}

function getActiveScopeFilters() {
  const selected = [...document.querySelectorAll('[data-doc-scope]:checked')]
    .map((input) => input.value)
    .filter((value) => value && value !== '__all__');
  return selected.length ? { doc_filter: selected } : {};
}

function toggleExport(event) {
  event.stopPropagation();
  document.getElementById('exp-menu')?.classList.toggle('open');
}

function filterVisibleSources(sources) {
  return (Array.isArray(sources) ? sources : []).filter((source) => source?.__kind !== 'assistant_meta');
}

function renderSourcesHtml(sources) {
  const visibleSources = filterVisibleSources(sources);
  if (!visibleSources.length) return '';
  return `<div class="msg-sources">참고: ${visibleSources.map(renderSourceBadgeHtml).join('')}</div>`;
}

function renderSourceBadgeHtml(source) {
  const label = escapeHTML(formatSource(source));
  const preview = sourcePreviewText(source);
  const previewAttrs = preview
    ? ` data-source-preview="${escapeHTML(preview)}" title="${escapeHTML(preview)}"`
    : '';
  return `<span class="src-badge"${previewAttrs}>${label}</span>`;
}

function sourcePreviewText(source) {
  if (!source || typeof source === 'string') return '';
  return String(source.snippet || source.content || source.text || '').trim();
}

function extractAssistantUiPayload(sources) {
  const meta = (Array.isArray(sources) ? sources : []).find((source) => source?.__kind === 'assistant_meta');
  if (!meta) return null;
  return {
    graphResult: meta.graph_result || null,
    warnings: Array.isArray(meta.warnings) ? meta.warnings : [],
    claimSnapshot: meta.claim_snapshot || null,
  };
}

async function exportChat(format) {
  document.getElementById('exp-menu')?.classList.remove('open');
  if (!currentSession) {
    toast('내보낼 채팅 세션이 없습니다.', 'warn');
    return;
  }
  try {
    const response = await apiFetch(
      `/sessions/${encodeURIComponent(currentSession)}/export?fmt=${encodeURIComponent(format)}`,
      { method: 'GET' }
    );
    const blob = await response.blob();
    const filename = `chat_${currentSession}.${format}`;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    toast(`${format.toUpperCase()} 파일로 내보냈습니다.`, 'success');
  } catch (error) {
    toast(error.message || '내보내기 중 오류가 발생했습니다.', 'error');
  }
}

export {
  formatSelectedModelLabel,
  getActiveScopeFilters,
  hasRenderableGraphPayload,
  isReasoningSupportedModel,
  renderCanonicalDecisionHtml,
  renderClarificationHtml,
  renderSourcesHtml,
  sanitizeAssistantAnswer,
  renderGraphReviewPathsHtml,
  renderGraphFactsHtml,
};

function getSelectedModel() {
  return localStorage.getItem(STORAGE_KEYS.SELECTED_LLM_MODEL) || 'sglang:qwen3-next-80b-a3b-instruct-fp8';
}

function isReasoningSupportedModel(modelId) {
  return String(modelId || '').toLowerCase().includes('qwen3-next-80b-a3b-thinking-fp8');
}

function getReasoningMode() {
  if (!isReasoningSupportedModel(getSelectedModel())) return 'off';
  return localStorage.getItem(STORAGE_KEYS.QWEN_REASONING_MODE) === 'on' ? 'on' : 'off';
}

function updateReasoningToggleVisibility() {
  const wrap = document.getElementById('reasoning-toggle-wrap');
  const toggle = document.getElementById('reasoning-mode-toggle');
  if (!wrap || !toggle) return;

  const supported = isReasoningSupportedModel(getSelectedModel());
  wrap.classList.toggle('hidden', !supported);
  toggle.disabled = !supported;
  toggle.checked = supported && getReasoningMode() === 'on';
}

function formatSelectedModelLabel(modelId) {
  const value = String(modelId || '').trim();
  if (!value) return '미확인';

  const [, raw = value] = value.split(':', 2);
  if (value === 'sglang:qwen3-next-80b-a3b-instruct-fp8') return 'SGLang · Qwen3 Next 80B Instruct';
  if (value === 'sglang:gpt-oss-20b') return 'SGLang · GPT-OSS 20B';
  if (value.startsWith('sglang:')) return `SGLang · ${raw}`;
  if (value.startsWith('vllm:')) return `vLLM · ${raw}`;
  if (value.startsWith('ollama:')) return `Ollama · ${raw}`;
  if (value.startsWith('openai:')) return `OpenAI · ${raw}`;
  return raw;
}

function getPolicyGeneration() {
  return document.querySelector('input[name="claim-policy-generation"]:checked')?.value || '5th';
}

function getSpecialCalculationStatus() {
  return document.querySelector('input[name="claim-special-calculation"]:checked')?.value || 'unknown';
}

function specialCalculationLabel(value) {
  if (value === 'applied') return '산정특례 적용';
  if (value === 'not_applied') return '산정특례 미적용';
  return '산정특례 여부 모름';
}

function getIndexMode() {
  const mode = document.querySelector('input[name="ocr-index"]:checked')?.value || 'v2_only';
  return mode === 'default' ? 'v2_only' : mode;
}

function getTopK() {
  return Number(document.querySelector('.range-input[min="1"]')?.value || 5);
}

function getTemperature() {
  return Number((document.querySelector('.range-input[min="0"]')?.value || 3) / 10);
}

function isAutoParamsEnabled() {
  return localStorage.getItem(STORAGE_KEYS.AUTO_RAG_PARAMS) !== 'off';
}

function syncAutoParamControls() {
  const enabled = isAutoParamsEnabled();
  const toggle = document.getElementById('auto-param-toggle');
  if (toggle) toggle.checked = enabled;
  document.querySelectorAll('.manual-param-control, #manual-param-divider').forEach((element) => {
    element.classList.toggle('hidden', enabled);
  });
}

function toggleAdaptiveKSettings(event) {
  event.preventDefault();
  const wrap = document.getElementById('adaptive-k-wrap');
  if (!wrap) return;
  wrap.classList.toggle('open');
}
