const importedTestModule = await import(process.env.E2E_PLAYWRIGHT_TEST_MODULE || '@playwright/test');
const { test, expect } = importedTestModule.default ?? importedTestModule;

test('protected live smoke only reads health, model state, and the login page', async ({ page, request }) => {
  const browserWriteRequests = [];
  page.on('request', (browserRequest) => {
    if (browserRequest.method() !== 'GET' && browserRequest.method() !== 'HEAD') {
      browserWriteRequests.push(`${browserRequest.method()} ${new URL(browserRequest.url()).pathname}`);
    }
  });

  const health = await request.get('/api/health');
  expect(health.ok()).toBe(true);
  const models = await request.get('/api/system/models');
  expect(models.ok()).toBe(true);

  await page.goto('/login');
  await expect(page.getByText('기동 중인 LLM', { exact: true })).toBeVisible();
  await expect(page.locator('#login-submit-btn')).toBeVisible();
  expect(browserWriteRequests).toEqual([]);
});
