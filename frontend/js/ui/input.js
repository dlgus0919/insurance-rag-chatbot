export class Input {
  constructor(options = {}) {
    this.options = {
      type: 'text',
      disabled: false,
      required: false,
      ...options,
    };
    this.element = null;
    this.errorElement = null;
    this.handlers = {
      onChange: this.options.onChange || null,
      onFocus: this.options.onFocus || null,
      onBlur: this.options.onBlur || null,
    };
  }

  create() {
    const input = document.createElement('input');
    input.type = this.options.type;

    if (this.options.id) {
      input.id = this.options.id;
    }

    if (this.options.name) {
      input.name = this.options.name;
    }

    if (this.options.placeholder) {
      input.placeholder = this.options.placeholder;
    }

    if (this.options.value) {
      input.value = this.options.value;
    }

    if (this.options.disabled) {
      input.disabled = true;
    }

    if (this.options.required) {
      input.required = true;
    }

    const classes = ['input-field'];
    if (this.options.className) {
      classes.push(this.options.className);
    }
    input.className = classes.join(' ');

    if (this.handlers.onChange) {
      input.addEventListener('change', this.handlers.onChange);
    }

    if (this.handlers.onFocus) {
      input.addEventListener('focus', this.handlers.onFocus);
    }

    if (this.handlers.onBlur) {
      input.addEventListener('blur', this.handlers.onBlur);
    }

    this.element = input;
    return input;
  }

  getValue() {
    return this.element?.value || '';
  }

  setValue(value) {
    if (this.element) {
      this.element.value = value;
    }
  }

  setDisabled(disabled) {
    if (this.element) {
      this.element.disabled = disabled;
    }
  }

  showError(message) {
    if (!this.element) return;

    this.element.classList.add('input-error');

    if (this.errorElement) {
      this.errorElement.remove();
    }

    this.errorElement = document.createElement('span');
    this.errorElement.className = 'input-error-text';
    this.errorElement.textContent = message;

    this.element.parentElement?.appendChild(this.errorElement);
  }

  clearError() {
    if (this.element) {
      this.element.classList.remove('input-error');
    }

    if (this.errorElement) {
      this.errorElement.remove();
      this.errorElement = null;
    }
  }

  focus() {
    this.element?.focus();
  }

  destroy() {
    if (this.element) {
      if (this.handlers.onChange) {
        this.element.removeEventListener('change', this.handlers.onChange);
      }
      if (this.handlers.onFocus) {
        this.element.removeEventListener('focus', this.handlers.onFocus);
      }
      if (this.handlers.onBlur) {
        this.element.removeEventListener('blur', this.handlers.onBlur);
      }

      this.clearError();
      this.element.remove();
      this.element = null;
    }
  }
}

export function createInput(options) {
  const input = new Input(options);
  return input.create();
}

export const inputPresets = {
  text: (id, placeholder) => createInput({
    type: 'text',
    id,
    placeholder,
  }),
  password: (id, placeholder) => createInput({
    type: 'password',
    id,
    placeholder,
  }),
  email: (id, placeholder) => createInput({
    type: 'email',
    id,
    placeholder,
  }),
  number: (id, placeholder) => createInput({
    type: 'number',
    id,
    placeholder,
  }),
  date: (id, placeholder) => createInput({
    type: 'date',
    id,
    placeholder,
  }),
};
