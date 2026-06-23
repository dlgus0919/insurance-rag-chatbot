import { test, expect } from '@playwright/test';

// Helper function to mock the SSE chat stream with custom payloads
async function mockChatStream(page, graphPayload = null, extraTokens = "테스트 답변", delayMs = 300) {
  let chatRequestPayloads = [];
  await page.route('**/api/chat/stream', async (route) => {
    if (delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
    const request = route.request();
    if (request.method() === 'POST') {
      chatRequestPayloads.push(request.postDataJSON());
    }

    const isSecondCall = chatRequestPayloads.length > 1;
    const sseBody = isSecondCall ? [
      'event: status',
      'data: {"message":"재검색 중"}',
      '',
      'event: sources',
      'data: [{"filename":"정답_약관.pdf","page":5}]',
      '',
      'event: token',
      'data: {"t":"재검색 결과 정답입니다."}',
      '',
      'event: done',
      'data: {"session_id":"e2e-session"}',
      '',
      '',
    ] : [
      'event: status',
      'data: {"message":"검색 중"}',
      '',
      'event: sources',
      'data: [{"filename":"약관.pdf","page":3}]',
      '',
      ...(graphPayload ? [
        'event: graph',
        `data: ${JSON.stringify(graphPayload)}`,
        ''
      ] : []),
      'event: token',
      `data: {"t":"${extraTokens}"}`,
      '',
      'event: done',
      'data: {"session_id":"e2e-session"}',
      '',
      '',
    ];

    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: sseBody.join('\n'),
    });
  });

  return chatRequestPayloads;
}

async function mockUserAuth(page) {
  const userPayload = {
    username: 'user',
    id: 'user',
    role: 'user',
    display_name: '사용자',
    created_at: '2026-06-05T00:00:00+09:00',
    password_updated_at: '2026-06-05T00:00:00+09:00',
  };
  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user: userPayload,
        access_expires_in: 900,
      }),
    });
  });
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(userPayload),
    });
  });
}

test.describe('채팅 플로우', () => {
  test.beforeEach(async ({ page }) => {
    await mockUserAuth(page);
    await page.goto('/login');
    await page.fill('#lid', 'user');
    await page.fill('#lpw', 'user1234');
    await page.click('#login-submit-btn');
    await expect(page).toHaveURL('/chat');
  });

  test('새 채팅 버튼 클릭 시 환영 메시지 표시', async ({ page }) => {
    await mockChatStream(page);
    await page.click('[data-action="new-chat"]');
    await expect(page.locator('.chat-welcome')).toBeVisible();
  });

  test('suggestion chip 클릭 시 사용자 메시지가 추가됨', async ({ page }) => {
    await mockChatStream(page);
    await page.click('.sug-chip:first-child');
    await expect(page.locator('.msg-row.user')).toBeVisible();
  });

  test('채팅 메시지 전송 중 입력창 disabled 흐름 확인', async ({ page }) => {
    await mockChatStream(page);
    await page.fill('#chat-input', '테스트 질문입니다');
    await page.keyboard.press('Enter');

    await expect(page.locator('#chat-input')).toBeDisabled();
    await expect(page.locator('#typing')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#typing')).toBeHidden({ timeout: 30000 });
    await expect(page.locator('#chat-input')).toBeEnabled();
  });

  test('GraphDB 구조화 검토 경로와 근거를 렌더링', async ({ page }) => {
    const graphPayload = {
      graph_review_paths: [
        {
          path_type_label: '보상 검토',
          status_label: '검토 필요',
          summary: '합병증 여부와 진단서를 함께 확인해야 합니다.',
          required_evidence: ['진단서'],
          review_actions: ['합병증 진단 확인'],
        },
      ],
      facts: [
        {
          subject: '대장내시경',
          relation: 'HAS_GRADE',
          object: '2종',
          status: 'confirmed',
          evidence: [{ doc_short: '실무가이드', page_start: 12 }],
        },
        {
          subject: '합병증',
          relation: 'RELATES_TO_COMPLICATION',
          object: '검토 후보',
          status: 'candidate',
        },
      ],
    };
    await mockChatStream(page, graphPayload, '테스트 답변');

    await page.fill('#chat-input', '합병증 감염 검토가 필요합니다');
    await page.keyboard.press('Enter');

    const reviewPaths = page.locator('.graph-review-paths');
    await expect(reviewPaths).toBeVisible({ timeout: 30000 });
    await expect(reviewPaths).toContainText('구조화 검토 경로');
    await expect(reviewPaths).toContainText('보상 검토');
    await expect(reviewPaths).toContainText('검토 필요');
    await expect(reviewPaths).toContainText('진단서');
    await expect(reviewPaths).toContainText('합병증 진단 확인');

    const facts = page.locator('.graph-facts');
    await expect(facts).toBeVisible();
    await expect(facts.locator('.graph-confirmed')).toContainText('대장내시경');
    await expect(facts.locator('.graph-candidate')).toContainText('합병증');
  });

  test('명확화 계획을 읽기 전용 패널로 렌더링', async ({ page }) => {
    const graphPayload = {
      plan: {
        normalized_terms: { "엠알아이": "MRI" },
        term_correction_candidates: [
          { raw: "엠알아이", normalized: "MRI", confidence: 0.72, source: "safe_candidate_rule" }
        ],
        ambiguous_terms: ["실손 세대", "방문 구분"],
        clarification_questions: ["어느 실손 세대 기준인지 확인해 주세요."]
      }
    };
    await mockChatStream(page, graphPayload, "모호한 답변");

    await page.fill('#chat-input', '엠알아이 보상돼?');
    await page.keyboard.press('Enter');
    await expect(page.locator('#typing')).toBeHidden({ timeout: 10000 });

    const clarification = page.locator('.msg-clarifications').last();
    await expect(clarification).toBeVisible();

    await expect(clarification).toContainText('추가 확인 필요');
    await expect(clarification).toContainText('실손 세대');
    await expect(clarification).toContainText('방문 구분');
    await expect(clarification).toContainText('추가 확인 질문');
    await expect(clarification).toContainText('어느 실손 세대 기준인지 확인해 주세요.');
    await expect(clarification).toContainText('입력 용어 정규화');
    await expect(clarification).toContainText('엠알아이 → MRI');
    await expect(clarification).toContainText('입력 용어 보정 후보');
    await expect(clarification).toContainText('(확인 필요)');
  });
});

test.describe('Qwen Thinking 추론 모드 토글', () => {
  test.beforeEach(async ({ page }) => {
    await mockUserAuth(page);
    await page.route('**/api/system/models', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          providers: {
            local: [
              {
                provider: 'local',
                id: 'sglang:qwen3-next-80b-a3b-thinking-fp8',
                label: 'Local · SGLang · Qwen3 Next Thinking',
              },
              {
                provider: 'local',
                id: 'sglang:gpt-oss-20b',
                label: 'Local · SGLang · GPT-OSS 20B',
              },
            ],
            openai: [],
          },
          defaults: { local: 'sglang:qwen3-next-80b-a3b-thinking-fp8', openai: null },
        }),
      });
    });
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
  });

  test('모델 선택 없이 추론 토글이 payload에 반영됨', async ({ page }) => {
    const payloads = await mockChatStream(page, null, '추론 토글 테스트 답변', 0);

    await page.goto('/login');
    await page.fill('#lid', 'user');
    await page.fill('#lpw', 'user1234');
    await page.click('#login-submit-btn');
    await expect(page).toHaveURL('/chat');

    await expect(page.locator('#active-model-select')).toHaveCount(0);
    await expect(page.locator('#reasoning-toggle-wrap')).not.toHaveClass(/hidden/);
    await page.check('#reasoning-mode-toggle');
    await page.fill('#chat-input', '추론 모드 payload 테스트');
    await page.keyboard.press('Enter');
    await expect.poll(() => payloads.length).toBeGreaterThan(0);

    expect(payloads[0].model).toBe('sglang:qwen3-next-80b-a3b-thinking-fp8');
    expect(payloads[0].reasoning_mode).toBe('on');
  });
});
