const importedTestModule = await import(process.env.E2E_PLAYWRIGHT_TEST_MODULE || '@playwright/test');
const { test, expect } = importedTestModule.default ?? importedTestModule;

const username = process.env.E2E_TEST_USERNAME || '';
const password = process.env.E2E_TEST_PASSWORD || '';

if (!username || !password) {
  throw new Error('isolated claim E2E requires runtime-only test credentials');
}

function postBody(request) {
  const payload = request.postData();
  return payload ? JSON.parse(payload) : {};
}

test('candidate selection preserves MX122 and connects the same claim thread to a follow-up', async ({ page }) => {
  const claimPayloads = [];
  const chatPayloads = [];

  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/claim/calculate' && request.method() === 'POST') {
      claimPayloads.push(postBody(request));
    }
    if (pathname === '/api/chat/stream' && request.method() === 'POST') {
      chatPayloads.push(postBody(request));
    }
  });

  await page.route('**/api/system/models', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        providers: {
          local: [{ id: 'sglang:isolated-e2e', label: '격리 E2E LLM' }],
        },
        defaults: { answer_primary: 'sglang:isolated-e2e' },
      }),
    });
  });

  await page.goto('/login');
  await expect(page.getByText('기동 중인 LLM', { exact: true })).toBeVisible();
  await page.locator('#lid').fill(username);
  await page.locator('#lpw').fill(password);
  await Promise.all([
    page.waitForURL(/\/chat$/),
    page.locator('#login-submit-btn').click(),
  ]);

  await page.locator('[data-mode="claim"]').click();
  await page.locator('input[name="claim-policy-generation"][value="4th"]').check();
  await page.locator('input[name="claim-special-calculation"][value="unknown"]').check();
  await page.locator('#claim-visit-type').selectOption('outpatient');
  await page.locator('.claim-item-name').fill('도수치료');
  await page.locator('.claim-nonpay-amount').fill('500000');
  await page.locator('[data-action="send-claim"]').click();

  await expect.poll(() => claimPayloads.length, { timeout: 30000 }).toBe(1);
  expect(claimPayloads[0]).toMatchObject({
    items: [{ input_name: '도수치료', input_code: '', nonpay_amount: '500000' }],
    context: {
      visit_type: 'outpatient',
      policy_generation: '4th',
      special_calculation_status: 'unknown',
    },
  });

  const mx122Candidate = page.locator('.candidate-btn[data-code="MX122"]');
  await expect(mx122Candidate).toBeVisible({ timeout: 30000 });
  const selectedResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === '/api/claim/calculate'
      && response.request().method() === 'POST'
      && response.status() === 200
  );
  await mx122Candidate.click();
  const selectedResult = await (await selectedResponse).json();

  await expect.poll(() => claimPayloads.length, { timeout: 30000 }).toBe(2);
  expect(claimPayloads[1].items[0].input_code).toBe('MX122');
  expect(selectedResult.session_id).toBeTruthy();
  expect(Number(selectedResult.deductible)).toBe(150000);
  expect(Number(selectedResult.payable_amount)).toBe(350000);
  expect(selectedResult.calculation_status).toBe('estimated_review_required');
  expect(selectedResult.line_results[0].calculation_status).toBe('calculated');
  expect(selectedResult.requires_review).toBe(true);

  const resultCard = page.locator('.claim-result').last();
  await expect(resultCard).toContainText('예상 공제금액');
  await expect(resultCard).toContainText('150,000원');
  await expect(resultCard).toContainText('350,000원');
  await expect(resultCard).toContainText('검토 사유');

  await page.locator('[data-mode="general"]').click();
  await expect(page.locator('#chat-input')).toBeVisible();
  const followUpRequest = page.waitForRequest((request) =>
    new URL(request.url()).pathname === '/api/chat/stream' && request.method() === 'POST'
  );
  await page.locator('#chat-input').fill('도수치료를 보상하지 않는다면');
  await page.locator('[data-action="send-message"]').click();
  await followUpRequest;

  await expect.poll(() => chatPayloads.length, { timeout: 30000 }).toBe(1);
  expect(chatPayloads[0].session_id).toBe(selectedResult.session_id);
  await expect(page.locator('.msg-row.bot .msg-bubble').last()).toContainText('예상 지급금액은 0원', {
    timeout: 30000,
  });
});

test('clarification selection carries the persisted session into the second chat turn', async ({ page }) => {
  const chatPayloads = [];
  const clarification = {
    request_id: 'isolated-clarification-001',
    slots: [
      {
        slot_id: 'treatment-purpose',
        question: '치료 목적인가요?',
        allowed_values: ['yes', 'no', 'unknown'],
      },
    ],
    query_scope: {
      route: 'general',
      policy_generation: '5th',
      doc_filter: [],
      index_mode: 'v2_only',
    },
  };
  const graphPayload = {
    schema_version: 2,
    display: { primary_text: '직접 조항의 적용 조건을 먼저 확인해야 합니다.' },
    evidence_assessment: {
      status: 'clarification_required',
      effect: 'review',
      conditions: [{ question: '치료 목적인가요?', state: 'unresolved' }],
      source_evidence: [{ doc_short: '표준약관', page_start: 9 }],
    },
    clarification: { pending_slots: clarification.slots },
  };

  await page.route('**/api/system/models', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        providers: { local: [{ id: 'sglang:isolated-e2e', label: '격리 E2E LLM' }] },
        defaults: { answer_primary: 'sglang:isolated-e2e' },
      }),
    });
  });
  await page.route('**/api/chat/stream', async (route) => {
    const payload = postBody(route.request());
    chatPayloads.push(payload);
    const secondTurn = chatPayloads.length === 2;
    const responseBody = secondTurn
      ? [
          'event: session',
          'data: {"session_id":"clarification-session","turn_id":"turn-follow-up"}',
          '',
          'event: final',
          'data: {"answer":"선택한 확인 내용을 반영해 계속 검토합니다."}',
          '',
          'event: done',
          'data: {"session_id":"clarification-session","persisted":true}',
          '',
          '',
        ].join('\n')
      : [
          'event: session',
          'data: {"session_id":"clarification-session","turn_id":"turn-first"}',
          '',
          'event: graph',
          `data: ${JSON.stringify(graphPayload)}`,
          '',
          'event: conversation',
          `data: ${JSON.stringify(clarification)}`,
          '',
          'event: final',
          'data: {"answer":"직접 조항의 적용 조건을 먼저 확인해야 합니다."}',
          '',
          'event: done',
          'data: {"session_id":"clarification-session","persisted":true}',
          '',
          '',
        ].join('\n');
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: responseBody,
    });
  });

  await page.goto('/login');
  await page.locator('#lid').fill(username);
  await page.locator('#lpw').fill(password);
  await Promise.all([
    page.waitForURL(/\/chat$/),
    page.locator('#login-submit-btn').click(),
  ]);

  await page.locator('#chat-input').fill('보상 조건을 검토해 주세요.');
  await page.locator('[data-action="send-message"]').click();
  const choice = page.locator('[data-clarification-value="yes"]');
  await expect(choice).toBeVisible({ timeout: 30000 });
  await choice.click();

  await expect.poll(() => chatPayloads.length, { timeout: 30000 }).toBe(2);
  expect(chatPayloads[0].turn_id).toMatch(/^turn-/);
  expect(chatPayloads[1]).toMatchObject({
    query: '예',
    session_id: 'clarification-session',
    clarification: {
      request_id: 'isolated-clarification-001',
      slot_id: 'treatment-purpose',
      value: 'yes',
    },
    policy_generation: '5th',
    index_mode: 'v2_only',
  });
  expect(chatPayloads[1].turn_id).toMatch(/^turn-/);
  expect(chatPayloads[1].turn_id).not.toBe(chatPayloads[0].turn_id);
  await expect(page.locator('.msg-row.bot .msg-bubble').last()).toContainText(
    '선택한 확인 내용을 반영해 계속 검토합니다.',
  );
});
