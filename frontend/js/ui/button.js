export class Button {
  constructor(options = {}) {
    this.options = {
      variant: 'primary',
      size: 'md',
      disabled: false,
      ...options,
    };
    this.element = null;
    this.clickHandler = this.options.onClick || null;
  }

  create() {
    const button = document.createElement('button');
    button.textContent = this.options.text;
    button.type = this.options.type || 'button';

    const classes = [
      'btn',
      `btn-${this.options.variant}`,
      `btn-${this.options.size}`,
    ];

    if (this.options.className) {
      classes.push(this.options.className);
    }

    button.className = classes.join(' ');

    if (this.options.id) {
      button.id = this.options.id;
    }

    if (this.options.disabled) {
      button.disabled = true;
    }

    if (this.options.title) {
      button.title = this.options.title;
    }

    if (this.clickHandler) {
      button.addEventListener('click', this.clickHandler);
    }

    this.element = button;
    return button;
  }

  setDisabled(disabled) {
    if (this.element) {
      this.element.disabled = disabled;
    }
  }

  setText(text) {
    if (this.element) {
      this.element.textContent = text;
    }
  }

  setClickHandler(handler) {
    if (this.element && this.clickHandler) {
      this.element.removeEventListener('click', this.clickHandler);
    }

    this.clickHandler = handler;

    if (this.element) {
      this.element.addEventListener('click', handler);
    }
  }

  destroy() {
    if (this.element) {
      if (this.clickHandler) {
        this.element.removeEventListener('click', this.clickHandler);
      }
      this.element.remove();
      this.element = null;
    }
  }
}

export function createButton(options) {
  const button = new Button(options);
  return button.create();
}

export const buttonPresets = {
  primary: (text, onClick) => createButton({
    text,
    variant: 'primary',
    size: 'md',
    onClick,
  }),
  secondary: (text, onClick) => createButton({
    text,
    variant: 'secondary',
    size: 'md',
    onClick,
  }),
  danger: (text, onClick) => createButton({
    text,
    variant: 'danger',
    size: 'md',
    onClick,
  }),
  text: (text, onClick) => createButton({
    text,
    variant: 'text',
    size: 'md',
    onClick,
  }),
  small: (text, onClick) => createButton({
    text,
    variant: 'primary',
    size: 'sm',
    onClick,
  }),
  large: (text, onClick) => createButton({
    text,
    variant: 'primary',
    size: 'lg',
    onClick,
  }),
};
