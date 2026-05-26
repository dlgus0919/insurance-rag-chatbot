import { STORAGE_KEYS } from '../config.js';
import { createConfirmModal } from '../modules/modal.js';
import { getCurrentSessionId, setCurrentSession } from '../modules/session.js';
import { setupMenuHandlers } from '../modules/sidebar.js';
import { toast } from '../modules/ui.js';
import { apiFetch, escapeHTML, formatSource, readSse } from '../utils.js';

const FALLBACK_LOGO_SRC = '';

let me = null;
let msgs = [];
let currentMode = 'general';
let currentSession = null;
let activeAbort = null;

export async function initChatPage({ currentUser, onGoAdmin, onLogout } = {}) {
  me = currentUser || null;

  applyUserToChatPage();
  renderWelcome();
  setupChatMenuHandlers({ onGoAdmin, onLogout });
  setupChatInput();
  setupChatDelegatedHandlers();
  setupSettingsHandlers();
  syncCurrentSessionFromActiveHistory();

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

    const actionTarget = target.closest('[data-action]');
    const action = actionTarget?.dataset.action;

    if (action === 'toggle-export') {
      toggleExport(event);
    } else if (action === 'send-quick') {
      await sendQuick();
    } else if (action === 'send-formal') {
      await sendFormal();
    } else if (action === 'send-claim') {
      await sendClaim();
    } else if (action === 'toggle-scope') {
      toggleScope(actionTarget);
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

  const page = document.getElementById('page-chat');
  if (page && !page.dataset.exportCloseBound) {
    page.dataset.exportCloseBound = 'true';
    page.addEventListener('click', (event) => {
      if (event.target.closest('.export-wrap')) return;
      document.getElementById('exp-menu')?.classList.remove('open');
    });
  }
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
  if (adminLink) adminLink.classList.toggle('hidden', me.role !== 'admin');
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
  msgs = [];
  currentSession = null;
  setCurrentSession(null);
  document.querySelectorAll('.history-item').forEach((item) => item.classList.remove('active'));
  renderWelcome();
  const input = document.getElementById('chat-input');
  if (input) input.value = '';
  toast('새 채팅이 시작되었습니다.');
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
    history.forEach((message) => appendMsg(message.role === 'assistant' ? 'bot' : message.role, message.content, message.sources || [], false));
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

function appendMsg(role, text, sources, track = true) {
  document.querySelector('.chat-welcome')?.remove();
  const container = document.getElementById('chat-msgs');
  if (!container) return;

  const time = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  const isUser = role === 'user';
  const sourceHtml = sources?.length
    ? `<div class="msg-sources">📄 참고: ${sources.map((source) => `<span class="src-badge">${escapeHTML(formatSource(source))}</span>`).join('')}</div>`
    : '';
  const row = document.createElement('div');
  row.className = `msg-row ${role}`;
  const avatar = isUser
    ? `<div class="msg-av usr">${me ? me.name[0] : 'U'}</div>`
    : `<div class="msg-av bot"><img src="${getBotLogoSrc()}" alt="AI"></div>`;
  row.innerHTML = `${avatar}<div><div class="msg-bubble">${escapeHTML(text).replace(/\n/g, '<br>')}${sourceHtml}</div><div class="msg-meta">${time}</div></div>`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  if (track) msgs.push({ role, text, time, sources: sources || [] });
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
  await streamChat(text, currentMode === 'quick' ? 'quickcode' : currentMode);
}

async function sendQuick() {
  const input = document.querySelector('#panel-quick .p-input');
  const term = input?.value.trim() || '백내장 수술';
  appendMsg('user', '[퀵코드 검색] ' + term);
  await streamChat(term, 'quickcode');
}

async function sendFormal() {
  const input = document.querySelector('#panel-formal .p-input');
  const memo = document.getElementById('formal-memo')?.value.trim() || '';
  const query = input?.value.trim() || 'N39.3 / 질병급여·비급여·3대비급여';
  const categories = [...document.querySelectorAll('.scenario-chip.active')].map((item) => item.textContent.trim());
  appendMsg('user', '[약관 정형] ' + query);
  await streamChat(query, 'formal', { product_category: categories }, memo);
}

async function sendClaim() {
  const itemName = document.getElementById('claim-item-name')?.value.trim() || '도수치료';
  const amount = document.getElementById('claim-amount')?.value.trim() || '150000';
  const quantity = document.getElementById('claim-quantity')?.value.trim() || '1';
  const code = document.getElementById('claim-item-code')?.value.trim() || 'MX122';
  const diagnosisCode = document.getElementById('claim-diagnosis-code')?.value.trim() || '';
  const coverageTopic = document.getElementById('claim-coverage-topic')?.value.trim() || '실손';
  const visitType = document.getElementById('claim-visit-type')?.value || '';
  const categoryHint = document.getElementById('claim-category-hint')?.value || '';
  const note = document.getElementById('claim-note')?.value.trim() || '';

  appendMsg('user', `[보험금 계산] ${itemName} / ${amount}원 / ${quantity}회`);
  await calculateClaim({
    items: [{
      input_name: itemName,
      input_code: code,
      claimed_amount: amount,
      quantity,
      user_category_hint: categoryHint,
    }],
    context: {
      visit_type: visitType,
      coverage_topic: coverageTopic,
      diagnosis_code: diagnosisCode,
      situation_note: note,
    },
    model: getSelectedModel(),
    top_k: getTopK(),
    index_mode: getIndexMode(),
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
    appendClaimResult(result);
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
      top_k: getTopK(),
      temperature: getTemperature(),
      filters,
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
        bubble.innerHTML = escapeHTML(answer).replace(/\n/g, '<br>');
      }
      if (event.event === 'final' && event.data.answer) {
        answer = event.data.answer;
        bubble.innerHTML = escapeHTML(answer).replace(/\n/g, '<br>');
      }
      if (event.event === 'done' && event.data.session_id) {
        currentSession = event.data.session_id;
        setCurrentSession(currentSession);
        if (event.data.answer) answer = event.data.answer;
      }
      if (event.event === 'error') throw new Error(event.data.message || '응답 생성 중 오류가 발생했습니다.');
    });
    if (!answer) answer = '응답이 비어 있습니다.';
    bubble.innerHTML = escapeHTML(answer).replace(/\n/g, '<br>')
      + renderWarningHtml(warnings)
      + renderGraphFactsHtml(graphResult)
      + (sources.length ? `<div class="msg-sources">📄 참고: ${sources.map((source) => `<span class="src-badge">${escapeHTML(formatSource(source))}</span>`).join('')}</div>` : '');
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

function renderClaimResultHtml(result) {
  const reviewClass = result.requires_review ? 'claim-review' : 'claim-ok';
  const reviewLabel = result.requires_review ? '검토 필요' : '계산 완료';
  const reasons = result.review_reasons?.length
    ? `<div class="claim-section"><div class="evidence-title">검토 사유</div><ul>${result.review_reasons.map((reason) => `<li>${escapeHTML(reason)}</li>`).join('')}</ul></div>`
    : '';
  const warnings = result.warnings?.length
    ? `<div class="claim-section claim-warning"><div class="evidence-title">처리 경고</div><ul>${result.warnings.map((warning) => `<li>${escapeHTML(warning)}</li>`).join('')}</ul></div>`
    : '';
  const candidates = result.candidates?.length
    ? `<div class="claim-section"><div class="evidence-title">선택 후보</div><ul>${result.candidates.slice(0, 6).map((candidate) => `<li>${escapeHTML(candidate.code || '')} ${escapeHTML(candidate.name || '')}</li>`).join('')}</ul></div>`
    : '';
  const basis = result.applied_basis?.length
    ? `<div class="claim-section"><div class="evidence-title">적용 근거</div><ul>${result.applied_basis.slice(0, 6).map((basisItem) => `<li><strong>${escapeHTML(basisItem.source || '근거')}</strong>: ${escapeHTML(basisItem.content || '')}</li>`).join('')}</ul></div>`
    : '';

  return `
    <div class="claim-result">
      <div class="claim-status ${reviewClass}">${reviewLabel}</div>
      <div class="claim-summary-grid">
        <div><span>총 청구금액</span><strong>${formatMoney(result.claimed_amount)}원</strong></div>
        <div><span>예상 공제금액</span><strong>${formatMoney(result.deductible)}원</strong></div>
        <div><span>예상 지급금액</span><strong>${formatMoney(result.payable_amount)}원</strong></div>
      </div>
      <div class="claim-note-text">${escapeHTML(result.notes || '')}</div>
      ${warnings}
      ${reasons}
      ${candidates}
      ${basis}
    </div>`;
}

function claimResultToText(result) {
  const lines = [
    `보험금 계산 결과: ${result.requires_review ? '검토 필요' : '계산 완료'}`,
    `총 청구금액: ${formatMoney(result.claimed_amount)}원`,
    `예상 공제금액: ${formatMoney(result.deductible)}원`,
    `예상 지급금액: ${formatMoney(result.payable_amount)}원`,
  ];
  if (result.review_reasons?.length) {
    lines.push(`검토 사유: ${result.review_reasons.join(' / ')}`);
  }
  return lines.join('\n');
}

function formatMoney(value) {
  const numeric = Number(String(value || '0').replace(/,/g, ''));
  if (!Number.isFinite(numeric)) return escapeHTML(value || '0');
  return numeric.toLocaleString('ko-KR');
}

function renderWarningHtml(warnings) {
  if (!warnings?.length) return '';
  const items = warnings
    .map((warning) => `<li>${escapeHTML(warning.message || warning.code || '처리 중 경고가 발생했습니다.')}</li>`)
    .join('');
  return `<div class="msg-warnings"><div class="evidence-title">처리 경고</div><ul>${items}</ul></div>`;
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

function setMode(mode, element) {
  if (mode === currentMode) return;
  currentMode = mode;
  document.querySelectorAll('.mode-tab').forEach((tab) => tab.classList.remove('active'));
  element.classList.add('active');
  document.getElementById('panel-quick')?.classList.remove('visible');
  document.getElementById('panel-formal')?.classList.remove('visible');
  document.getElementById('panel-claim')?.classList.remove('visible');
  if (mode === 'quick') document.getElementById('panel-quick')?.classList.add('visible');
  if (mode === 'formal') document.getElementById('panel-formal')?.classList.add('visible');
  if (mode === 'claim') document.getElementById('panel-claim')?.classList.add('visible');
  msgs = [];
  renderWelcome();
}

function autoH(element) {
  element.style.height = 'auto';
  element.style.height = Math.min(element.scrollHeight, 120) + 'px';
}

function toggleScope(element) {
  document.querySelectorAll('.scope-chip').forEach((chip) => chip.classList.remove('active'));
  element.classList.add('active');
}

function toggleExport(event) {
  event.stopPropagation();
  document.getElementById('exp-menu')?.classList.toggle('open');
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

function getSelectedModel() {
  return localStorage.getItem(STORAGE_KEYS.SELECTED_LLM_MODEL) || 'ollama:exaone3.5:7.8b';
}

function getIndexMode() {
  return document.querySelector('input[name="ocr-index"]:checked')?.value || 'default';
}

function getTopK() {
  return Number(document.querySelector('.range-input[min="1"]')?.value || 5);
}

function getTemperature() {
  return Number((document.querySelector('.range-input[min="0"]')?.value || 3) / 10);
}
