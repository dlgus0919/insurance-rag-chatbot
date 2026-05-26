export class Toast {
  constructor(options = {}) {
    this.options = {
      type: 'info',
      duration: 3000,
      position: 'top-right',
      ...options,
    };

    this.element = null;
    this.timeoutId = null;
  }

  create() {
    const toast = document.createElement('div');
    toast.className = `toast toast-${this.options.type}`;

    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.innerHTML = this.getIcon(this.options.type);

    const message = document.createElement('span');
    message.className = 'toast-message';
    message.textContent = this.options.message;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close';
    closeBtn.textContent = 'x';
    closeBtn.addEventListener('click', () => this.close());

    toast.appendChild(icon);
    toast.appendChild(message);
    toast.appendChild(closeBtn);

    this.element = toast;
    return toast;
  }

  getIcon(type) {
    const icons = {
      info: 'i',
      success: '✓',
      warning: '!',
      error: 'x',
    };
    return icons[type] || 'i';
  }

  show() {
    if (!this.element) {
      this.create();
    }

    let container = document.querySelector(`.toast-container.${this.options.position}`);
    if (!container) {
      container = document.createElement('div');
      container.className = `toast-container ${this.options.position}`;
      document.body.appendChild(container);
    }

    container.appendChild(this.element);

    requestAnimationFrame(() => {
      this.element?.classList.add('show');
    });

    if (this.options.duration > 0) {
      this.timeoutId = setTimeout(() => this.close(), this.options.duration);
    }
  }

  close() {
    if (this.timeoutId) {
      clearTimeout(this.timeoutId);
    }

    this.element?.classList.remove('show');

    setTimeout(() => {
      if (this.element?.parentElement) {
        this.element.remove();
      }

      if (this.options.onClose) {
        this.options.onClose();
      }
    }, 300);
  }

  destroy() {
    this.close();
    this.element = null;
  }
}

export function showToast(message, type = 'info', duration = 3000) {
  const toast = new Toast({
    message,
    type,
    duration,
  });

  toast.show();
  return toast;
}

export function showSuccess(message, duration = 3000) {
  return showToast(message, 'success', duration);
}

export function showError(message, duration = 5000) {
  return showToast(message, 'error', duration);
}

export function showWarning(message, duration = 4000) {
  return showToast(message, 'warning', duration);
}

export function showInfo(message, duration = 3000) {
  return showToast(message, 'info', duration);
}
