export function toast(message, type = 'info') {
  const existingToast = document.getElementById('toast');
  if (existingToast) {
    existingToast.textContent = message;
    existingToast.className = `toast-active ${type}`;
    existingToast.style.opacity = '1';
    setTimeout(() => {
      existingToast.style.opacity = '0';
    }, 2500);
    return;
  }

  console.log(`[${type.toUpperCase()}] ${message}`);
}

export function openModal(id) {
  document.getElementById(id)?.classList.add('open');
}

export function closeModal(id) {
  document.getElementById(id)?.classList.remove('open');
}

let resetTargetUserId = null;

export function setResetTargetUser(userId) {
  resetTargetUserId = userId;
}

export function getResetTargetUser() {
  return resetTargetUserId;
}
