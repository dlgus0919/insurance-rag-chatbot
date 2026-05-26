import { test, expect } from '@playwright/test';

test.describe('채팅 플로우', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/chat/stream', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 300));
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: [
          'event: status',
          'data: {"message":"검색 중"}',
          '',
          'event: sources',
          'data: [{"filename":"약관.pdf","page":3}]',
          '',
          'event: token',
          'data: {"t":"테스트 답변"}',
          '',
          'event: done',
          'data: {"session_id":"e2e-session"}',
          '',
          '',
        ].join('\n'),
      });
    });

    await page.goto('/login');
    await page.fill('#lid', 'user');
    await page.fill('#lpw', 'user1234');
    await page.click('#login-submit-btn');
    await expect(page).toHaveURL('/chat');
  });

  test('새 채팅 버튼 클릭 시 환영 메시지 표시', async ({ page }) => {
    await page.click('[data-action="new-chat"]');
    await expect(page.locator('.chat-welcome')).toBeVisible();
  });

  test('suggestion chip 클릭 시 사용자 메시지가 추가됨', async ({ page }) => {
    await page.click('.sug-chip:first-child');
    await expect(page.locator('.msg-row.user')).toBeVisible();
  });

  test('채팅 메시지 전송 중 입력창 disabled 흐름 확인', async ({ page }) => {
    await page.fill('#chat-input', '테스트 질문입니다');
    await page.keyboard.press('Enter');

    await expect(page.locator('#chat-input')).toBeDisabled();
    await expect(page.locator('#typing')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#typing')).toBeHidden({ timeout: 30000 });
    await expect(page.locator('#chat-input')).toBeEnabled();
  });
});
