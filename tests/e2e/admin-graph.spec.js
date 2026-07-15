import { test, expect } from '@playwright/test';

const adminUser = {
  username: 'admin',
  id: 'admin',
  role: 'admin',
  display_name: '관리자',
  created_at: '2026-07-15T00:00:00+09:00',
  password_updated_at: '2026-07-15T00:00:00+09:00',
};

const overview = {
  nodes: [
    { id: 'category', label: '수술 분류', node_type: 'SurgeryCategory', degree: 1, score: 8, confidence: 1 },
    { id: 'procedure', label: '수술 A', node_type: 'SurgeryProcedure', degree: 1, score: 4, confidence: 1 },
  ],
  edges: [
    { id: 'edge-1', source: 'procedure', target: 'category', edge_type: 'HAS_CATEGORY', semantic_role: 'overview' },
  ],
  meta: { node_limit: 120, edge_limit: 240 },
};

async function mockAdminApis(page) {
  const counts = { neighborhood: 0 };
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body = {};

    if (path === '/api/auth/login') body = { user: adminUser, access_expires_in: 900 };
    else if (path === '/api/auth/me') body = adminUser;
    else if (path === '/api/system/models') {
      body = {
        providers: { local: [{ id: 'sglang:test-model', label: '테스트 모델' }] },
        defaults: { answer: 'sglang:test-model' },
      };
    }
    else if (path === '/api/sessions') body = { items: [], total: 0 };
    else if (path === '/api/admin/logs' || path === '/api/admin/users') body = { items: [], total: 0 };
    else if (path === '/api/admin/stats') body = {};
    else if (path === '/api/admin/system-summary') body = { indices: [], assets: {}, llm: {}, embedding: {} };
    else if (path === '/api/admin/rag-diagnostics/latest') body = { available: false };
    else if (path === '/api/admin/graph-vector-sync') body = { available: false };
    else if (path === '/api/admin/graph/overview') body = overview;
    else if (path === '/api/admin/graph/search') {
      body = { items: [{ id: 'procedure', label: '수술 A', node_type: 'SurgeryProcedure', degree: 1, match_kind: 'exact' }], total: 1 };
    } else if (path === '/api/admin/graph/nodes/procedure/neighborhood') {
      counts.neighborhood += 1;
      body = { ...overview, meta: { ...overview.meta, center_node_id: 'procedure' } };
    } else if (path === '/api/admin/graph/nodes/procedure') {
      body = {
        id: 'procedure', label: '수술 A', node_type: 'SurgeryProcedure', degree: 1,
        confidence: 1, aliases: ['수술가'], connection_counts: { hierarchy: 1, related: 0 },
        evidence: [{ doc_short: '약관', page_start: 10, page_end: 11 }],
      };
    } else if (path.startsWith('/api/admin/knowledge/')) body = { items: [], total: 0 };

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return counts;
}

async function installFakeGraphBundle(page) {
  await page.route('**/dist/graph-viz.min.js*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `
        window.__graphCameraCalls = 0;
        window.InsuranceGraph3D = () => (container) => {
          const canvas = document.createElement('canvas');
          container.appendChild(canvas);
          const graph = {};
          ['backgroundColor','nodeId','nodeLabel','nodeAutoColorBy','nodeVal','linkSource','linkTarget','linkOpacity','linkWidth','cooldownTime','warmupTicks','enableNodeDrag','graphData','width','height'].forEach((name) => graph[name] = () => graph);
          graph.renderer = () => ({ setPixelRatio() {} });
          graph.onNodeClick = (handler) => { window.__graphClick = handler; return graph; };
          graph.pauseAnimation = () => {};
          graph.resumeAnimation = () => {};
          graph.cameraPosition = () => { window.__graphCameraCalls += 1; };
          graph._destructor = () => {};
          return graph;
        };
      `,
    });
  });
}

async function loginAsAdmin(page) {
  await page.goto('/login');
  await page.fill('#lid', 'admin');
  await page.fill('#lpw', 'admin1234');
  await page.click('#login-submit-btn');
  await expect(page).toHaveURL('/chat');
  await page.goto('/admin');
  await expect(page).toHaveURL('/admin');
}

test('GraphDB admin flow supports search, focus, detail, reset and repeated tab entry', async ({ page }) => {
  const counts = await mockAdminApis(page);
  await installFakeGraphBundle(page);
  await loginAsAdmin(page);

  await page.click('[data-admin-sub="graph"]');
  await expect(page.locator('#admin-graph-status')).toContainText('2개 개념');
  await page.fill('#admin-graph-search-input', '수술 A');
  await page.press('#admin-graph-search-input', 'Enter');
  await page.click('[data-graph-node-id="procedure"]');
  await expect(page.locator('#admin-graph-detail')).toContainText('약관 p.10-11');
  await expect.poll(() => page.evaluate(() => window.__graphCameraCalls)).toBe(1);

  await page.evaluate(() => window.__graphClick?.({ id: 'procedure', x: 4, y: 2, z: 1 }));
  await expect.poll(() => page.evaluate(() => window.__graphCameraCalls)).toBe(2);
  await expect.poll(() => counts.neighborhood).toBe(2);

  await page.click('[data-admin-sub="logs"]');
  await page.click('[data-admin-sub="graph"]');
  await page.evaluate(() => window.__graphClick?.({ id: 'procedure', x: 4, y: 2, z: 1 }));
  await expect.poll(() => counts.neighborhood).toBe(3);
  await page.click('[data-graph-action="overview"]');
  await expect(page.locator('#admin-graph-status')).toContainText('2개 개념');
});

test('GraphDB admin flow uses a keyboard-selectable 2d fallback when WebGL bundle is unavailable', async ({ page }) => {
  await mockAdminApis(page);
  await page.route('**/dist/graph-viz.min.js*', (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
  await loginAsAdmin(page);

  await page.click('[data-admin-sub="graph"]');
  const fallbackButton = page.locator('.graph-fallback [data-graph-node-id="procedure"]');
  await expect(fallbackButton).toBeVisible();
  await fallbackButton.focus();
  await expect(fallbackButton).toBeFocused();
});

test('self-hosted 3d bundle survives 30 focus and reset cycles', async ({ page }) => {
  test.setTimeout(120000);
  await mockAdminApis(page);
  await loginAsAdmin(page);
  await page.evaluate(() => {
    window.__graphContextLosses = 0;
    window.addEventListener('webglcontextlost', () => { window.__graphContextLosses += 1; }, true);
  });

  const overviewStarted = Date.now();
  await page.click('[data-admin-sub="graph"]');
  await expect(page.locator('#admin-graph-status')).toContainText('2개 개념');
  const overviewMs = Date.now() - overviewStarted;
  await expect(page.locator('#admin-graph-canvas canvas')).toBeVisible();

  await page.fill('#admin-graph-search-input', '수술 A');
  await page.press('#admin-graph-search-input', 'Enter');
  const result = page.locator('[data-graph-node-id="procedure"]').first();
  await expect(result).toBeVisible();

  await page.evaluate(() => {
    window.__graphFrameSample = null;
    const started = performance.now();
    let frames = 0;
    const sample = (now) => {
      frames += 1;
      if (now - started >= 2000) {
        window.__graphFrameSample = { frames, elapsedMs: now - started };
        return;
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });

  const cycleStarted = Date.now();
  for (let index = 0; index < 30; index += 1) {
    await result.click();
    await expect(page.locator('#admin-graph-detail')).toContainText('약관 p.10-11');
    await page.click('[data-graph-action="overview"]');
    await expect(page.locator('#admin-graph-status')).toContainText('2개 개념');
  }
  const cycleMs = Date.now() - cycleStarted;
  await expect.poll(() => page.evaluate(() => window.__graphFrameSample)).not.toBeNull();

  const metrics = await page.evaluate(() => ({
    contextLosses: window.__graphContextLosses,
    frameSample: window.__graphFrameSample,
    heapBytes: performance.memory?.usedJSHeapSize || null,
  }));
  const fps = metrics.frameSample.frames * 1000 / metrics.frameSample.elapsedMs;

  expect(overviewMs).toBeLessThanOrEqual(2000);
  expect(fps).toBeGreaterThanOrEqual(30);
  expect(metrics.contextLosses).toBe(0);
  console.log('DGX_GRAPH_BROWSER_METRICS', JSON.stringify({ overviewMs, cycleMs, fps, ...metrics }));
});
