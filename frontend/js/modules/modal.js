export class Modal {
  constructor(options = {}) {
    this.id = options.id || `modal-${Date.now()}`;
    this.title = options.title || '';
    this.content = options.content || '';
    this.onConfirm = options.onConfirm || null;
    this.onCancel = options.onCancel || null;
    this.confirmText = options.confirmText || '확인';
    this.cancelText = options.cancelText || '취소';
    this.isOpen = false;
    this.element = null;

    this.create();
  }

  create() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.setAttribute('data-modal-id', this.id);

    const modal = document.createElement('div');
    modal.className = 'modal modal-dialog';

    const header = document.createElement('div');
    header.className = 'modal-header';

    const titleElement = document.createElement('h2');
    titleElement.className = 'modal-title';
    titleElement.textContent = this.title;
    header.appendChild(titleElement);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'modal-close';
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', '닫기');
    closeBtn.innerHTML = '&times;';
    closeBtn.addEventListener('click', () => this.hide());
    header.appendChild(closeBtn);

    const body = document.createElement('div');
    body.className = 'modal-body';
    if (typeof this.content === 'string') {
      body.innerHTML = this.content;
    } else {
      body.appendChild(this.content);
    }

    const footer = document.createElement('div');
    footer.className = 'modal-footer';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn-secondary';
    cancelBtn.type = 'button';
    cancelBtn.textContent = this.cancelText;
    cancelBtn.addEventListener('click', () => {
      if (this.onCancel) this.onCancel();
      this.hide();
    });
    footer.appendChild(cancelBtn);

    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn-primary';
    confirmBtn.type = 'button';
    confirmBtn.textContent = this.confirmText;
    confirmBtn.addEventListener('click', async () => {
      if (confirmBtn.disabled) return;

      confirmBtn.disabled = true;
      try {
        if (this.onConfirm) await this.onConfirm();
      } catch (error) {
        console.error('Modal confirm failed:', error);
      } finally {
        confirmBtn.disabled = false;
        this.hide();
      }
    });
    footer.appendChild(confirmBtn);

    modal.appendChild(header);
    modal.appendChild(body);
    modal.appendChild(footer);

    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) this.hide();
    });

    overlay.appendChild(modal);
    this.element = overlay;
  }

  show() {
    if (!this.element) this.create();
    if (!document.body.contains(this.element)) {
      document.body.appendChild(this.element);
    }

    this.element.classList.add('active', 'show');
    this.isOpen = true;
  }

  hide() {
    if (this.element) {
      this.element.classList.remove('active', 'show');
    }
    this.isOpen = false;
  }

  destroy() {
    if (this.element && document.body.contains(this.element)) {
      document.body.removeChild(this.element);
    }
    this.element = null;
  }

  isVisible() {
    return this.isOpen;
  }
}

export function createConfirmModal(title, message, onConfirm, onCancel) {
  return new Modal({
    title,
    content: message,
    onConfirm,
    onCancel,
    confirmText: '확인',
    cancelText: '취소',
  });
}

export function createAlertModal(title, message, onClose) {
  const modal = new Modal({
    title,
    content: message,
    onConfirm: onClose,
    confirmText: '확인',
  });

  setTimeout(() => {
    const cancelBtn = modal.element.querySelector('.btn-secondary');
    if (cancelBtn) cancelBtn.style.display = 'none';
  }, 0);

  return modal;
}

export function createInputModal(title, label, placeholder, onConfirm) {
  const inputContainer = document.createElement('div');
  inputContainer.innerHTML = `
    <label>${label}</label>
    <input type="text" class="modal-input" placeholder="${placeholder}" />
  `;

  const modal = new Modal({
    title,
    content: inputContainer,
    onConfirm: () => {
      const input = modal.element.querySelector('.modal-input');
      if (onConfirm) onConfirm(input.value);
    },
    confirmText: '확인',
    cancelText: '취소',
  });

  return modal;
}

export function closeAllModals() {
  document.querySelectorAll('.modal-overlay.active, .modal-overlay.show').forEach((overlay) => {
    overlay.classList.remove('active', 'show');
  });
}
