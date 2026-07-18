import path from 'node:path';
import { fileURLToPath } from 'node:url';

const testModule = process.env.E2E_PLAYWRIGHT_TEST_MODULE || '@playwright/test';
const importedTestModule = await import(testModule);
const { defineConfig, devices } = importedTestModule.default ?? importedTestModule;
const projectRoot = path.dirname(fileURLToPath(import.meta.url));
const baseURL = process.env.BASE_URL || '';
const artifactsDir = process.env.E2E_ARTIFACTS_DIR || '';

function requireIsolatedWriteTarget() {
  if (process.env.E2E_ISOLATED_TARGET !== '1') {
    throw new Error('isolated browser E2E requires E2E_ISOLATED_TARGET=1');
  }
  if (process.env.INSURANCE_RAG_E2E_ALLOW_WRITES !== '1') {
    throw new Error('isolated browser E2E requires explicit write opt-in');
  }
  if (!process.env.E2E_TEST_USERNAME || !process.env.E2E_TEST_PASSWORD) {
    throw new Error('isolated browser E2E requires runtime-only test credentials');
  }
  if (!baseURL || !artifactsDir) {
    throw new Error('isolated browser E2E requires BASE_URL and E2E_ARTIFACTS_DIR');
  }
  const target = new URL(baseURL);
  const isLoopback = ['127.0.0.1', 'localhost', '::1'].includes(target.hostname);
  if (target.protocol !== 'http:' || !isLoopback || !target.port || target.port === '18080') {
    throw new Error('isolated browser E2E refuses non-loopback and protected live targets');
  }
  if (!path.isAbsolute(artifactsDir)) {
    throw new Error('E2E_ARTIFACTS_DIR must be an absolute isolated path');
  }
}

requireIsolatedWriteTarget();

export default defineConfig({
  testDir: path.join(projectRoot, 'tests', 'e2e'),
  testMatch: 'isolated-claim-flow.spec.js',
  timeout: 60000,
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
