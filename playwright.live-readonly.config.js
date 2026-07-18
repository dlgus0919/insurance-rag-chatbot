import path from 'node:path';
import { fileURLToPath } from 'node:url';

const testModule = process.env.E2E_PLAYWRIGHT_TEST_MODULE || '@playwright/test';
const importedTestModule = await import(testModule);
const { defineConfig, devices } = importedTestModule.default ?? importedTestModule;
const projectRoot = path.dirname(fileURLToPath(import.meta.url));
const baseURL = process.env.BASE_URL || '';
const artifactsDir = process.env.E2E_ARTIFACTS_DIR || '';

function requireReadOnlyLiveTarget() {
  if (process.env.E2E_READ_ONLY_TARGET !== '1') {
    throw new Error('protected live smoke requires E2E_READ_ONLY_TARGET=1');
  }
  if (process.env.INSURANCE_RAG_E2E_ALLOW_WRITES === '1' || process.env.E2E_ISOLATED_TARGET === '1') {
    throw new Error('protected live smoke refuses a write-enabled browser target');
  }
  if (!baseURL || !artifactsDir) {
    throw new Error('protected live smoke requires BASE_URL and E2E_ARTIFACTS_DIR');
  }
  const target = new URL(baseURL);
  const isLoopback = ['127.0.0.1', 'localhost', '::1'].includes(target.hostname);
  if (target.protocol !== 'http:' || !isLoopback || target.port !== '18080' || target.pathname !== '/') {
    throw new Error('protected live smoke only permits the loopback 18080 root target');
  }
  if (!path.isAbsolute(artifactsDir)) {
    throw new Error('E2E_ARTIFACTS_DIR must be an absolute artifact path');
  }
}

requireReadOnlyLiveTarget();

export default defineConfig({
  testDir: path.join(projectRoot, 'tests', 'e2e'),
  testMatch: 'live-readonly-smoke.spec.js',
  timeout: 30000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: artifactsDir,
  use: {
    baseURL,
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
