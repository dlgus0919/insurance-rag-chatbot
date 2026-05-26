import { createAlertModal } from '../modules/modal.js';
import { showError } from '../ui/notification.js';
import { STORAGE_KEYS } from '../config.js';
import { isEmpty } from '../utils.js';

export async function initLoginPage({ onLogin } = {}) {
  const loginButton = document.querySelector('.lp-btn');
  const usernameInput = document.getElementById('lid') || document.getElementById('username');
  const passwordInput = document.getElementById('lpw') || document.getElementById('password');

  setupPasswordToggle();
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
      const selectedModel = document.querySelector('input[name="llm-model"]:checked')?.value || 'gemma4';
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
  const selectedModel = localStorage.getItem(STORAGE_KEYS.SELECTED_LLM_MODEL) || 'gemma4';
  const radio = document.querySelector(`input[name="llm-model"][value="${selectedModel}"]`);
  if (radio) radio.checked = true;
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
