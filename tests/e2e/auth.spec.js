import { test, expect } from '@playwright/test';

test.describe('인증 플로우', () => {
  test('일반 사용자 로그인 후 채팅 페이지 진입', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#lid', 'user');
    await page.fill('#lpw', 'user1234');
    await page.click('#login-submit-btn');

    await expect(page).toHaveURL('/chat');
    await expect(page.locator('#page-chat')).toHaveClass(/active/);
    await expect(page.locator('#admin-link')).toHaveClass(/hidden/);
  });

  test('관리자 로그인 후 관리자 링크 표시', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#lid', 'admin');
    await page.fill('#lpw', 'admin1234');
    await page.click('#login-submit-btn');

    await expect(page).toHaveURL('/chat');
    await expect(page.locator('#admin-link')).not.toHaveClass(/hidden/);
  });

  test('잘못된 비밀번호 로그인 실패 시 비밀번호 필드 초기화', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#lid', 'user');
    await page.fill('#lpw', 'wrongpassword');
    await page.click('#login-submit-btn');

    await expect(page).toHaveURL('/login');
    await expect(page.locator('#lpw')).toHaveValue('');
  });

  test('로그아웃 버튼 확인 후 로그인 페이지 이동', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#lid', 'user');
    await page.fill('#lpw', 'user1234');
    await page.click('#login-submit-btn');
    await expect(page).toHaveURL('/chat');

    await page.click('#logout-btn');
    const modal = page.locator('.modal-overlay.active');
    await expect(modal).toBeVisible();
    await expect(modal).toContainText('정말 로그아웃하시겠습니까?');
    await modal.locator('.btn-primary').click();

    await expect(page).toHaveURL('/login');
    await expect(page.locator('#page-login')).toHaveClass(/active/);
  });

  test('미인증 상태에서 /chat 직접 접근 시 /login 리다이렉트', async ({ page }) => {
    await page.goto('/chat');
    await expect(page).toHaveURL('/login');
  });
});
