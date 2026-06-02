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

test.describe('채팅 플로우', () => {
  test.beforeEach(async ({ page }) => {
    // Only go to login page and perform login with correct user fixture
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

  test('명확화 UX 선택값 요약 칩 및 단일 선택 그룹 테스트', async ({ page }) => {
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

    const summary = clarification.locator('[data-clarify-summary]');
    await expect(summary).toContainText('아직 선택된 조건이 없습니다.');

    // 1. 단일 보정 용어 선택
    const mriBtn = clarification.locator('.clarify-option', { hasText: 'MRI 맞음' });
    await mriBtn.click();
    await expect(mriBtn).toHaveClass(/selected/);
    await expect(summary).toContainText('MRI');

    // 2. 단일 선택 그룹 테스트 (4세대 클릭 후 5세대 클릭 시 독점 선택 확인)
    const fourthBtn = clarification.locator('.clarify-option', { hasText: '4세대 실손' });
    const fifthBtn = clarification.locator('.clarify-option', { hasText: '5세대 실손' });

    await fourthBtn.click();
    await expect(fourthBtn).toHaveClass(/selected/);
    await expect(fifthBtn).not.toHaveClass(/selected/);
    await expect(summary).toContainText('4세대 실손');

    await fifthBtn.click();
    await expect(fifthBtn).toHaveClass(/selected/);
    await expect(fourthBtn).not.toHaveClass(/selected/);
    await expect(summary).toContainText('5세대 실손');
    await expect(summary).not.toContainText('4세대 실손');
  });

  test('명확화 UX 선택 초기화 테스트', async ({ page }) => {
    const graphPayload = {
      plan: {
        ambiguous_terms: ["실손 세대", "방문 구분"],
        clarification_questions: ["추가 정보 필요"]
      }
    };
    await mockChatStream(page, graphPayload);

    await page.fill('#chat-input', '실손 보상 기준?');
    await page.keyboard.press('Enter');
    await expect(page.locator('#typing')).toBeHidden({ timeout: 10000 });

    const clarification = page.locator('.msg-clarifications').last();
    const applyBtn = clarification.locator('[data-action="apply-clarification"]');
    const resetBtn = clarification.locator('[data-action="reset-clarification"]');
    const summary = clarification.locator('[data-clarify-summary]');

    await expect(applyBtn).toBeDisabled();
    await expect(resetBtn).toBeDisabled();

    // 조건 선택
    const fifthBtn = clarification.locator('.clarify-option', { hasText: '5세대 실손' });
    const tongBtn = clarification.locator('.clarify-option', { hasText: '통원' });
    await fifthBtn.click();
    await tongBtn.click();

    await expect(applyBtn).toBeEnabled();
    await expect(resetBtn).toBeEnabled();
    await expect(summary).toContainText('5세대 실손');
    await expect(summary).toContainText('통원');

    // 초기화 클릭
    await resetBtn.click();

    await expect(fifthBtn).not.toHaveClass(/selected/);
    await expect(tongBtn).not.toHaveClass(/selected/);
    await expect(summary).toContainText('아직 선택된 조건이 없습니다.');
    await expect(applyBtn).toBeDisabled();
    await expect(resetBtn).toBeDisabled();
  });

  test('명확화 UX 자주 쓰는 조건 프리셋 테스트', async ({ page }) => {
    const graphPayload = {
      plan: {
        normalized_terms: { "엠알아이": "MRI" },
        term_correction_candidates: [
          { raw: "엠알아이", normalized: "MRI" }
        ],
        ambiguous_terms: ["실손 세대", "방문 구분"]
      }
    };
    const chatRequestPayloads = await mockChatStream(page, graphPayload);

    await page.fill('#chat-input', '엠알아이 통원 보상?');
    await page.keyboard.press('Enter');
    await expect(page.locator('#typing')).toBeHidden({ timeout: 10000 });

    const clarification = page.locator('.msg-clarifications').last();
    const summary = clarification.locator('[data-clarify-summary]');
    const applyBtn = clarification.locator('[data-action="apply-clarification"]');

    // 프리셋 버튼 '5세대 + 통원' 클릭
    const presetBtn = clarification.locator('.clarify-preset[data-preset-id="fifth-outpatient"]');
    await presetBtn.click();

    await expect(summary).toContainText('5세대 실손');
    await expect(summary).toContainText('통원');
    await expect(applyBtn).toBeEnabled();

    // 다시 검색 클릭
    await applyBtn.click();
    await expect(page.locator('#typing')).toBeHidden({ timeout: 10000 });

    // Payload 검증
    expect(chatRequestPayloads.length).toBe(2);
    const secondReq = chatRequestPayloads[1];
    expect(secondReq.query).toContain('엠알아이 통원 보상?');
    expect(secondReq.query).toContain('[사용자 명확화]');
    expect(secondReq.query).toContain('- 실손 세대: 5세대');
    expect(secondReq.query).toContain('- 방문 구분: 통원');

    // clarification payload 검증
    expect(secondReq.clarification.selections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ group: 'policy_generation', value: '5세대' }),
        expect.objectContaining({ group: 'visit_type', value: '통원' }),
      ])
    );
  });

  test('명확화 UX는 화면에 없는 조건을 프리셋으로 합성하지 않는다', async ({ page }) => {
    const graphPayload = {
      plan: {
        ambiguous_terms: ["실손 세대", "방문 구분"]
      }
    };
    const chatRequestPayloads = await mockChatStream(page, graphPayload);

    await page.fill('#chat-input', '도수치료 실손?');
    await page.keyboard.press('Enter');
    await expect(page.locator('#typing')).toBeHidden({ timeout: 10000 });

    const clarification = page.locator('.msg-clarifications').last();
    const summary = clarification.locator('[data-clarify-summary]');
    const applyBtn = clarification.locator('[data-action="apply-clarification"]');

    // coverage_topic 개별 선택지가 없는 상황에서는 해당 값을 포함한 프리셋을 숨긴다.
    const presetBtn = clarification.locator('.clarify-preset[data-preset-id="manual-shockwave-fifth-outpatient"]');
    await expect(presetBtn).toHaveCount(0);

    const basicPresetBtn = clarification.locator('.clarify-preset[data-preset-id="fifth-outpatient"]');
    await basicPresetBtn.click();

    await expect(summary).not.toContainText('도수/충격파');
    await expect(summary).toContainText('5세대 실손');
    await expect(summary).toContainText('통원');

    // 다시 검색 클릭
    await applyBtn.click();
    await expect(page.locator('#typing')).toBeHidden({ timeout: 10000 });

    // Payload 검증
    expect(chatRequestPayloads.length).toBe(2);
    const secondReq = chatRequestPayloads[1];
    expect(secondReq.query).toContain('[사용자 명확화]');
    expect(secondReq.query).toContain('- 실손 세대: 5세대');
    expect(secondReq.query).toContain('- 방문 구분: 통원');

    expect(secondReq.clarification.selections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ group: 'policy_generation', value: '5세대' }),
        expect.objectContaining({ group: 'visit_type', value: '통원' }),
      ])
    );
  });

  test('명확화 UX 복수 선택 그룹 테스트 (증빙 서류)', async ({ page }) => {
    const graphPayload = {
      plan: {
        ambiguous_terms: ["증빙 서류"],
        clarification_questions: ["진료비 영수증, 세부내역서, 진단서 등 확인 필요"]
      }
    };
    const chatRequestPayloads = await mockChatStream(page, graphPayload);

    await page.fill('#chat-input', '구비 서류 뭐 필요해?');
    await page.keyboard.press('Enter');
    await expect(page.locator('#typing')).toBeHidden({ timeout: 10000 });

    const clarification = page.locator('.msg-clarifications').last();
    const summary = clarification.locator('[data-clarify-summary]');
    const applyBtn = clarification.locator('[data-action="apply-clarification"]');

    const receiptBtn = clarification.locator('.clarify-option', { hasText: '영수증' });
    const statementBtn = clarification.locator('.clarify-option', { hasText: '세부내역서' });

    // 둘 다 클릭
    await receiptBtn.click();
    await statementBtn.click();

    // 두 버튼 모두 selected 및 요약에 모두 들어갔는지 확인 (복수 선택 작동)
    await expect(receiptBtn).toHaveClass(/selected/);
    await expect(statementBtn).toHaveClass(/selected/);
    await expect(summary).toContainText('영수증');
    await expect(summary).toContainText('세부내역서');

    // 다시 검색 클릭
    await applyBtn.click();
    await expect(page.locator('#typing')).toBeHidden({ timeout: 10000 });

    // Payload 검증
    expect(chatRequestPayloads.length).toBe(2);
    const secondReq = chatRequestPayloads[1];
    expect(secondReq.query).toContain('[사용자 명확화]');
    expect(secondReq.query).toContain('- 증빙 서류: 영수증');
    expect(secondReq.query).toContain('- 증빙 서류: 세부내역서');

    expect(secondReq.clarification.selections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ group: 'evidence_tags', value: '영수증' }),
        expect.objectContaining({ group: 'evidence_tags', value: '세부내역서' }),
      ])
    );
  });
});
