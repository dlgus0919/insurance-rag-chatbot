import test from 'node:test';
import assert from 'node:assert/strict';

class MemoryStorage {
  constructor() {
    this.values = new Map();
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }

  removeItem(key) {
    this.values.delete(key);
  }

  clear() {
    this.values.clear();
  }
}

test('auth token and user use session storage only', async () => {
  globalThis.localStorage = new MemoryStorage();
  globalThis.sessionStorage = new MemoryStorage();

  const storage = await import('../frontend/js/storage.js');
  const { STORAGE_KEYS } = await import('../frontend/js/config.js');

  localStorage.setItem(STORAGE_KEYS.TOKEN, 'legacy-token');
  localStorage.setItem(STORAGE_KEYS.USER, JSON.stringify({ username: 'legacy' }));

  assert.equal(storage.getToken(), null);
  assert.equal(storage.getUser(), null);

  storage.setToken('session-token');
  storage.setUser({ username: 'admin', role: 'admin' });

  assert.equal(sessionStorage.getItem(STORAGE_KEYS.TOKEN), 'session-token');
  assert.equal(localStorage.getItem(STORAGE_KEYS.TOKEN), null);
  assert.deepEqual(storage.getUser(), { username: 'admin', role: 'admin' });
  assert.equal(localStorage.getItem(STORAGE_KEYS.USER), null);

  storage.removeToken();
  storage.removeUser();

  assert.equal(sessionStorage.getItem(STORAGE_KEYS.TOKEN), null);
  assert.equal(sessionStorage.getItem(STORAGE_KEYS.USER), null);
});
