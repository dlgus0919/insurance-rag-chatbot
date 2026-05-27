import { createAlertModal } from '../modules/modal.js';
import { showError } from '../ui/notification.js';
import { fetchAPI } from '../api.js';
import { STORAGE_KEYS } from '../config.js';
import { escapeHTML, isEmpty } from '../utils.js';

export async function initLoginPage({ onLogin } = {}) {
  const loginButton = document.querySelector('.lp-btn');
  const usernameInput = document.getElementById('lid') || document.getElementById('username');
  const passwordInput = document.getElementById('lpw') || document.getElementById('password');

  setupPasswordToggle();
  await renderAvailableModelOptions();
  restoreSelectedModel();

  if (!loginButton || !usernameInput || !passwordInput || loginButton.dataset.phase2Bound) {
    return;
  }

  loginButton.dataset.phase2Bound = 'true';
  loginButton.addEventListener('click', async () => {
    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    if (isEmpty(username) || isEmpty(password)) {
      showError('사용자명과 비밀번호를 입력해주세요.');
      createAlertModal('입력 오류', '사용자명과 비밀번호를 입력해주세요.', null).show();
      return;
    }

    if (onLogin) {
      const selectedModel = document.querySelector('input[name="llm-model"]:checked')?.value;
      if (!selectedModel) {
        showError('현재 서버에서 사용 가능한 LLM 모델이 없습니다.');
        createAlertModal('모델 선택 오류', '현재 서버에서 사용 가능한 LLM 모델이 없습니다. vLLM/SGLang/Ollama 상태를 확인해 주세요.', null).show();
        return;
      }
      localStorage.setItem(STORAGE_KEYS.SELECTED_LLM_MODEL, selectedModel);

      const originalText = loginButton.textContent;
      loginButton.disabled = true;
      loginButton.textContent = '로그인 중...';

      try {
        await onLogin(username, password);
      } finally {
        loginButton.disabled = false;
        loginButton.textContent = originalText;
      }
    }
  });

  [usernameInput, passwordInput].forEach((input) => {
    if (input.dataset.phase2EnterBound) return;
    input.dataset.phase2EnterBound = 'true';
    input.addEventListener('keypress', (event) => {
      if (event.key === 'Enter') {
        loginButton.click();
      }
    });
  });
}

function setupPasswordToggle() {
  const toggleBtn = document.querySelector('[data-action="toggle-password"]') || document.querySelector('.pw-toggle');
  const passwordInput = document.getElementById('lpw') || document.getElementById('password');

  if (!toggleBtn || !passwordInput || toggleBtn.dataset.phase2Bound) return;

  toggleBtn.dataset.phase2Bound = 'true';
  toggleBtn.addEventListener('click', () => {
    passwordInput.type = passwordInput.type === 'password' ? 'text' : 'password';
  });
}

function restoreSelectedModel() {
  const savedModel = localStorage.getItem(STORAGE_KEYS.SELECTED_LLM_MODEL);
  const radios = [...document.querySelectorAll('input[name="llm-model"]')];
  if (!radios.length) return;

  const savedRadio = savedModel ? radios.find((radio) => radio.value === savedModel) : null;
  const defaultRadio = radios.find((radio) => radio.dataset.default === 'true') || radios[0];
  const selectedRadio = savedRadio || defaultRadio;
  selectedRadio.checked = true;
  localStorage.setItem(STORAGE_KEYS.SELECTED_LLM_MODEL, selectedRadio.value);
}

async function renderAvailableModelOptions() {
  const group = document.getElementById('model-select-group');
  if (!group) return;

  try {
    const response = await fetchAPI('/system/models');
    const models = response.providers?.local || [];
    if (!models.length) {
      group.innerHTML = '<div class="lp-model-status">현재 서버에 로드되어 노출 가능한 로컬 LLM 모델이 없습니다.</div>';
      return;
    }

    const defaultIds = new Set(Object.values(response.defaults || {}).filter(Boolean));
    group.innerHTML = models.map((model, index) => renderModelOption(model, defaultIds.has(model.id) || index === 0)).join('');
  } catch (error) {
    console.warn('Failed to load model list:', error);
    group.innerHTML = '<div class="lp-model-status">모델 목록을 불러오지 못했습니다. 서버 상태를 확인해 주세요.</div>';
  }
}

function renderModelOption(model, isDefault) {
  return `
    <label class="lp-model-option" style="display: block;">
      <input type="radio" name="llm-model" value="${escapeHTML(model.id)}" data-default="${isDefault ? 'true' : 'false'}">
      <span class="lp-model-card">
        <span class="lp-model-name">${escapeHTML(model.label || model.id)}</span>
        <span class="lp-model-desc">${escapeHTML(describeModel(model.id))}</span>
      </span>
    </label>`;
}

function describeModel(modelId) {
  if (modelId.startsWith('vllm:')) return 'vLLM 서버에서 현재 서빙 중인 모델';
  if (modelId.startsWith('sglang:')) return 'SGLang 서버에서 현재 서빙 중인 모델';
  if (modelId.startsWith('ollama:')) return 'Ollama에 설치되어 사용 가능한 저부하 모델';
  if (modelId.startsWith('openai:')) return 'OpenAI API 설정이 있을 때 사용 가능한 클라우드 모델';
  return '서버에서 사용 가능하다고 보고된 모델';
}

export function initLoginCanvas() {
  const canvas = document.getElementById('networkCanvas');
  if (!canvas) return;
  const context = canvas.getContext('2d');
  let width = 0;
  let height = 0;
  let nodes = [];
  let animationId = null;

  function resize() {
    width = canvas.width = canvas.offsetWidth;
    height = canvas.height = canvas.offsetHeight;
  }

  function init() {
    resize();
    nodes = [];
    const count = Math.floor(width * height / 12000);
    for (let index = 0; index < count; index += 1) {
      nodes.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.2,
        vy: (Math.random() - 0.5) * 0.2,
        r: Math.random() * 1.4 + 0.5,
      });
    }
  }

  function draw() {
    context.clearRect(0, 0, width, height);
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < 125) {
          context.beginPath();
          context.moveTo(nodes[i].x, nodes[i].y);
          context.lineTo(nodes[j].x, nodes[j].y);
          context.strokeStyle = `rgba(77,145,255,${(1 - distance / 125) * 0.25})`;
          context.lineWidth = 0.7;
          context.stroke();
        }
      }
    }
    nodes.forEach((node) => {
      context.beginPath();
      context.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      context.fillStyle = 'rgba(77,145,255,0.55)';
      context.fill();
    });
  }

  function step() {
    if (!document.body.contains(canvas)) {
      animationId = null;
      return;
    }
    nodes.forEach((node) => {
      node.x += node.vx;
      node.y += node.vy;
      if (node.x < 0 || node.x > width) node.vx *= -1;
      if (node.y < 0 || node.y > height) node.vy *= -1;
    });
    draw();
    animationId = requestAnimationFrame(step);
  }

  function handleVisibility() {
    if (document.hidden) {
      if (animationId) {
        cancelAnimationFrame(animationId);
        animationId = null;
      }
      return;
    }

    if (!animationId && document.body.contains(canvas)) {
      step();
    }
  }

  window.addEventListener('resize', init);
  document.addEventListener('visibilitychange', handleVisibility);
  init();
  step();
}
