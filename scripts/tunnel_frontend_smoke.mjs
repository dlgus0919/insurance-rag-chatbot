import { chromium } from 'playwright';

const baseUrl = (
  process.env.FRONTEND_SMOKE_BASE_URL
  || process.env.E2E_BASE_URL
  || process.env.BASE_URL
  || 'http://127.0.0.1:18080'
).replace(/\/+$/, '');
const screenshotPath = process.env.FRONTEND_SMOKE_SCREENSHOT || '/tmp/insurance-rag-tunnel-login.png';
const allowNonLocal = process.env.FRONTEND_SMOKE_ALLOW_NONLOCAL === '1';

const parsedUrl = new URL(baseUrl);
const isLocalTunnel = ['127.0.0.1', 'localhost', '::1'].includes(parsedUrl.hostname);
if (!isLocalTunnel && !allowNonLocal) {
  throw new Error('Refusing a non-local URL. Set FRONTEND_SMOKE_ALLOW_NONLOCAL=1 only for an approved test host.');
}

const launchOptions = { headless: true };
if (process.env.PLAYWRIGHT_EXECUTABLE_PATH) {
  launchOptions.executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH;
} else if (process.env.PLAYWRIGHT_BROWSER_CHANNEL) {
  launchOptions.channel = process.env.PLAYWRIGHT_BROWSER_CHANNEL;
} else if (process.platform === 'darwin') {
  launchOptions.channel = 'chrome';
}

const browser = await chromium.launch(launchOptions);
try {
  const context = await browser.newContext();
  const healthResponse = await context.request.get(`${baseUrl}/api/health`, {
    failOnStatusCode: false,
  });
  if (!healthResponse.ok()) {
    throw new Error(`Health check failed with HTTP ${healthResponse.status()}`);
  }

  const page = await context.newPage();
  const navigation = await page.goto(`${baseUrl}/login`, {
    waitUntil: 'networkidle',
    timeout: 30_000,
  });
  if (!navigation?.ok()) {
    throw new Error(`Login page failed with HTTP ${navigation?.status() ?? 'unknown'}`);
  }

  const checks = {
    appRoot: await page.locator('#app').isVisible(),
    usernameField: await page.locator('#lid').isVisible(),
    passwordField: await page.locator('#lpw').isVisible(),
    loginButton: await page.locator('#login-submit-btn').isVisible(),
  };
  const failedChecks = Object.entries(checks).filter(([, passed]) => !passed).map(([name]) => name);
  if (failedChecks.length > 0) {
    throw new Error(`Login UI checks failed: ${failedChecks.join(', ')}`);
  }

  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log(JSON.stringify({
    mode: 'read-only',
    baseUrl,
    healthStatus: healthResponse.status(),
    loginStatus: navigation.status(),
    title: await page.title(),
    checks,
    screenshotPath,
  }, null, 2));
} finally {
  await browser.close();
}
