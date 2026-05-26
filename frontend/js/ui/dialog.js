export class Dialog {
  constructor(options = {}) {
    this.options = {
      type: 'default',
      closable: true,
      backdrop: true,
      size: 'md',
      buttons: [],
      ...options,
    };

    this.element = null;
    this.overlay = null;
    this.isVisible = false;
    this.buttonHandlers = new Map();
  }

  create() {
    this.overlay = document.createElement('div');
    this.overlay.className = 'dialog-overlay';
    if (!this.options.backdrop) {
      this.overlay.style.pointerEvents = 'none';
    }

    const dialog = document.createElement('div');
    dialog.className = `dialog dialog-${this.options.size} dialog-${this.options.type}`;

    const header = document.createElement('div');
    header.className = 'dialog-header';

    const title = document.createElement('h3');
    title.className = 'dialog-title';
    title.textContent = this.options.title;
    header.appendChild(title);

    if (this.options.closable) {
      const closeBtn = document.createElement('button');
      closeBtn.className = 'dialog-close';
      closeBtn.textContent = 'x';
      closeBtn.addEventListener('click', () => this.close());
      header.appendChild(closeBtn);
    }

    dialog.appendChild(header);

    const content = document.createElement('div');
    content.className = 'dialog-content';

    if (typeof this.options.content === 'string') {
      if (this.options.content.includes('<')) {
        content.innerHTML = this.options.content;
      } else {
        content.textContent = this.options.content;
      }
    } else if (this.options.content instanceof HTMLElement) {
      content.appendChild(this.options.content);
    }

    dialog.appendChild(content);

    if (this.options.buttons.length > 0) {
      const footer = document.createElement('div');
      footer.className = 'dialog-footer';

      this.options.buttons.forEach((btn) => {
        const button = document.createElement('button');
        button.className = `btn btn-${btn.variant || 'primary'}`;
        button.textContent = btn.text;

        const handler = btn.onClick || (() => this.close());
        this.buttonHandlers.set(button, handler);

        button.addEventListener('click', () => {
          handler();
        });

        footer.appendChild(button);
      });

      dialog.appendChild(footer);
    }

    if (this.options.backdrop) {
      this.overlay.addEventListener('click', (event) => {
        if (event.target === this.overlay) {
          this.close();
        }
      });
    }

    this.overlay.appendChild(dialog);
    this.element = dialog;

    return this.overlay;
  }

  show() {
    if (!this.element) {
      this.create();
    }

    if (!document.body.contains(this.overlay)) {
      document.body.appendChild(this.overlay);
    }

    requestAnimationFrame(() => {
      this.overlay.classList.add('active');
      this.element.classList.add('show');
    });

    this.isVisible = true;
  }

  close() {
    this.overlay?.classList.remove('active');
    this.element?.classList.remove('show');

    setTimeout(() => {
      if (this.overlay && document.body.contains(this.overlay)) {
        this.overlay.remove();
      }
      this.isVisible = false;

      if (this.options.onClose) {
        this.options.onClose();
      }
    }, 300);
  }

  setContent(content) {
    const contentEl = this.element?.querySelector('.dialog-content');
    if (contentEl) {
      if (typeof content === 'string') {
        contentEl.innerHTML = content;
      } else {
        contentEl.innerHTML = '';
        contentEl.appendChild(content);
      }
    }
  }

  setButtonDisabled(buttonIndex, disabled) {
    const buttons = this.element?.querySelectorAll('.dialog-footer button');
    if (buttons?.[buttonIndex]) {
      buttons[buttonIndex].disabled = disabled;
    }
  }

  destroy() {
    this.close();
    this.buttonHandlers.clear();
    this.element = null;
    this.overlay = null;
  }
}

export function createConfirmDialog(title, message, onConfirm, onCancel = null) {
  const dialog = new Dialog({
    title,
    content: message,
    type: 'confirm',
    buttons: [
      {
        text: '취소',
        variant: 'secondary',
        onClick: () => {
          if (onCancel) onCancel();
          dialog.close();
        },
      },
      {
        text: '확인',
        variant: 'primary',
        onClick: () => {
          onConfirm();
          dialog.close();
        },
      },
    ],
  });

  return dialog;
}

export function createAlertDialog(title, message, onClose = null) {
  const dialog = new Dialog({
    title,
    content: message,
    type: 'alert',
    buttons: [
      {
        text: '확인',
        variant: 'primary',
        onClick: () => {
          if (onClose) onClose();
          dialog.close();
        },
      },
    ],
  });

  return dialog;
}

export function createInputDialog(title, label, placeholder, onConfirm) {
  const inputId = `dialog-input-${Date.now()}`;

  const content = `
    <div class="dialog-form">
      <label for="${inputId}" class="dialog-label">${label}</label>
      <input type="text" id="${inputId}" class="input-field" placeholder="${placeholder}">
    </div>
  `;

  const dialog = new Dialog({
    title,
    content,
    type: 'form',
    buttons: [
      {
        text: '취소',
        variant: 'secondary',
        onClick: () => dialog.close(),
      },
      {
        text: '입력',
        variant: 'primary',
        onClick: () => {
          const input = document.getElementById(inputId);
          if (input?.value.trim()) {
            onConfirm(input.value);
            dialog.close();
          } else {
            input?.focus();
          }
        },
      },
    ],
  });

  setTimeout(() => {
    document.getElementById(inputId)?.focus();
  }, 0);

  return dialog;
}
