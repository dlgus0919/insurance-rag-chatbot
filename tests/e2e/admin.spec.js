import { test, expect } from '@playwright/test';

test.describe('관리자 접근 제어', () => {
  test('일반 사용자는 /admin 접근 불가', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#lid', 'user');
    await page.fill('#lpw', 'user1234');
    await page.click('#login-submit-btn');
    await expect(page).toHaveURL('/chat');

    await page.goto('/admin');
    await expect(page).toHaveURL('/chat');
    await expect(page.locator('#page-chat')).toHaveClass(/active/);
  });

  test('관리자는 /admin 접근 가능', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#lid', 'admin');
    await page.fill('#lpw', 'admin1234');
    await page.click('#login-submit-btn');
    await expect(page).toHaveURL('/chat');

    await page.goto('/admin');
    await expect(page).toHaveURL('/admin');
    await expect(page.locator('#page-admin')).toHaveClass(/active/);
  });

  test('관리자 페이지에서 사용자 목록 로드', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#lid', 'admin');
    await page.fill('#lpw', 'admin1234');
    await page.click('#login-submit-btn');
    await expect(page).toHaveURL('/chat');
    await page.goto('/admin');
    await expect(page).toHaveURL('/admin');

    await page.click('[data-admin-sub="users"]');
    await expect(page.locator('#sub-users tbody tr')).not.toHaveCount(0, { timeout: 10000 });
  });
});
