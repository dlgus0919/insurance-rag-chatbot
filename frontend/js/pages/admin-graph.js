import {
  fetchGraphNeighborhood,
  fetchGraphNodeDetail,
  fetchGraphOverview,
  searchGraphNodes,
} from '../modules/admin-graph.js';
import { escapeHTML } from '../utils.js';
import { canUseWebGL, createGraphRenderer } from '../graph/renderer-3d.js';

const DEFAULT_LIMITS = { nodeLimit: 120, edgeLimit: 240 };

export class GraphPageState {
  constructor() {
    this.mode = 'overview';
    this.selectedNodeId = null;
    this.graph = { nodes: [], edges: [] };
  }

  setGraph(payload, mode = this.mode) {
    this.graph = normalizeGraphPayload(payload, DEFAULT_LIMITS);
    this.mode = mode;
  }

  selectNode(nodeId) {
    this.selectedNodeId = nodeId;
  }

  resetOverview() {
    this.mode = 'overview';
    this.selectedNodeId = null;
  }
}

export function normalizeGraphPayload(payload = {}, limits = DEFAULT_LIMITS) {
  const nodeLimit = Math.min(Math.max(Number(limits.nodeLimit) || DEFAULT_LIMITS.nodeLimit, 1), 250);
  const edgeLimit = Math.min(Math.max(Number(limits.edgeLimit) || DEFAULT_LIMITS.edgeLimit, 1), 500);
  const nodes = Array.isArray(payload.nodes) ? payload.nodes.slice(0, nodeLimit) : [];
  const ids = new Set(nodes.map((node) => node.id));
  const edges = (Array.isArray(payload.edges) ? payload.edges : [])
    .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
    .slice(0, edgeLimit);
  return { nodes, edges, meta: payload.meta || {} };
}

export function renderGraphFallback(payload = {}) {
  const graph = normalizeGraphPayload(payload);
  const labels = new Map(graph.nodes.map((node) => [node.id, node.label || node.id]));
  const roleLabel = { parent: '상위', child: '하위', related: '연관', overview: '분류' };
  const nodeItems = graph.nodes.map((node) => `
    <li><button type="button" data-graph-node-id="${escapeHTML(node.id)}"><strong>${escapeHTML(node.label || node.id)}</strong><span>${escapeHTML(node.node_type || '개념')}</span></button></li>`).join('');
  const edgeItems = graph.edges.map((edge) => `
    <li>${escapeHTML(labels.get(edge.source) || edge.source)} <b>${roleLabel[edge.semantic_role] || '연관'}</b> ${escapeHTML(labels.get(edge.target) || edge.target)}</li>`).join('');
  return `<div class="graph-fallback"><p>3D 보기를 사용할 수 없어 관계 목록으로 표시합니다.</p><div><h3>개념</h3><ul>${nodeItems || '<li>표시할 개념이 없습니다.</li>'}</ul></div><div><h3>관계</h3><ul>${edgeItems || '<li>표시할 관계가 없습니다.</li>'}</ul></div></div>`;
}

let activeView = null;

export async function initAdminGraphPage() {
  disposeAdminGraphPage();
  const root = document.getElementById('sub-graph');
  if (!root) return;

  const view = {
    root,
    state: new GraphPageState(),
    renderer: null,
    abortController: new AbortController(),
    contextRecoveryAttempts: 0,
  };
  activeView = view;
  bindGraphView(view);

  await loadOverview(view);
}

export async function activateAdminGraphPage() {
  if (!activeView) {
    await initAdminGraphPage();
    return;
  }
  if (activeView.abortController.signal.aborted) {
    activeView.abortController = new AbortController();
  }
  bindGraphView(activeView);
  activeView.renderer?.resume();
  activeView.renderer?.resize();
}

export function deactivateAdminGraphPage() {
  if (!activeView) return;
  activeView.abortController.abort();
  activeView.renderer?.pause();
  unbindGraphView(activeView);
}

export function disposeAdminGraphPage() {
  if (!activeView) return;
  deactivateAdminGraphPage();
  activeView.renderer?.dispose();
  activeView = null;
}

function bindGraphView(view) {
  if (view.eventsBound) return;
  view.root.addEventListener('submit', onSearchSubmit);
  view.root.addEventListener('click', onGraphAction);
  window.addEventListener('resize', resizeGraphRenderer);
  view.eventsBound = true;
}

function unbindGraphView(view) {
  if (!view.eventsBound) return;
  view.root.removeEventListener('submit', onSearchSubmit);
  view.root.removeEventListener('click', onGraphAction);
  window.removeEventListener('resize', resizeGraphRenderer);
  view.eventsBound = false;
}

async function loadOverview(view) {
  setStatus(view, '핵심 구조를 불러오는 중입니다.');
  try {
    const payload = await fetchGraphOverview({ ...DEFAULT_LIMITS, signal: view.abortController.signal });
    if (activeView !== view) return;
    view.state.resetOverview();
    view.state.setGraph(payload, 'overview');
    view.contextRecoveryAttempts = 0;
    renderGraph(view);
    setStatus(view, `${view.state.graph.nodes.length}개 개념과 ${view.state.graph.edges.length}개 관계를 표시합니다.`);
  } catch (error) {
    if (error.name === 'AbortError' || activeView !== view) return;
    setStatus(view, error.message || 'GraphDB 핵심 구조를 불러오지 못했습니다.', true);
    renderFallback(view);
  }
}

async function onSearchSubmit(event) {
  if (!(event.target instanceof HTMLFormElement) || event.target.id !== 'admin-graph-search-form') return;
  event.preventDefault();
  const view = activeView;
  const input = view?.root.querySelector('#admin-graph-search-input');
  const query = input?.value.trim();
  const results = view?.root.querySelector('#admin-graph-search-results');
  if (!view || !results || !query) return;

  results.textContent = '검색 중입니다.';
  try {
    const payload = await searchGraphNodes(query, { signal: view.abortController.signal });
    if (activeView !== view) return;
    const items = Array.isArray(payload?.items) ? payload.items : [];
    results.innerHTML = items.length
      ? items.map((item) => `<button type="button" class="graph-search-result" data-graph-node-id="${escapeHTML(item.id)}">${escapeHTML(item.label)}<span>${escapeHTML(item.node_type)}</span></button>`).join('')
      : '<span class="graph-empty">일치하는 개념이 없습니다.</span>';
  } catch (error) {
    if (error.name !== 'AbortError' && activeView === view) results.textContent = error.message || '검색하지 못했습니다.';
  }
}

async function onGraphAction(event) {
  const target = event.target instanceof Element ? event.target.closest('[data-graph-action], [data-graph-node-id]') : null;
  if (!target || !activeView) return;
  if (target.dataset.graphNodeId) {
    await focusNode(activeView, target.dataset.graphNodeId);
    return;
  }
  if (target.dataset.graphAction === 'overview') await loadOverview(activeView);
  if (target.dataset.graphAction === 'toggle-related') {
    target.setAttribute('aria-pressed', target.getAttribute('aria-pressed') !== 'true' ? 'true' : 'false');
    if (activeView.state.selectedNodeId) await focusNode(activeView, activeView.state.selectedNodeId);
  }
}

async function focusNode(view, nodeId, { skipCamera = false } = {}) {
  if (!skipCamera) {
    const currentNode = view.state.graph.nodes.find((node) => node.id === nodeId);
    view.renderer?.focusNode(currentNode);
  }
  const includeRelated = view.root.querySelector('[data-graph-action="toggle-related"]')?.getAttribute('aria-pressed') === 'true';
  setStatus(view, '선택한 개념의 연결 구조를 불러오는 중입니다.');
  try {
    const [graphPayload, detail] = await Promise.all([
      fetchGraphNeighborhood(nodeId, { includeRelated, signal: view.abortController.signal }),
      fetchGraphNodeDetail(nodeId, { signal: view.abortController.signal }),
    ]);
    if (activeView !== view) return;
    view.state.setGraph(graphPayload, 'focus');
    view.state.selectNode(nodeId);
    view.contextRecoveryAttempts = 0;
    renderGraph(view);
    renderDetail(view, detail);
    setStatus(view, `${view.state.graph.nodes.length}개 개념을 표시합니다.`);
  } catch (error) {
    if (error.name === 'AbortError' || activeView !== view) return;
    setStatus(view, error.message || '선택한 개념을 불러오지 못했습니다.', true);
  }
}

function renderGraph(view) {
  const container = view.root.querySelector('#admin-graph-canvas');
  if (!container) return;
  view.renderer?.dispose();
  view.renderer = null;
  if (!canUseWebGL()) {
    renderFallback(view);
    return;
  }
  try {
    view.renderer = createGraphRenderer(container, {
      onNodeClick: (node) => focusNode(view, node.id, { skipCamera: true }),
      onContextLost: () => handleGraphContextLost(view),
    });
    if (!view.renderer) throw new Error('3D 그래프 번들을 사용할 수 없습니다.');
    view.renderer.resize();
    view.renderer.setGraph(view.state.graph);
  } catch {
    renderFallback(view);
  }
}

function renderFallback(view) {
  const container = view.root.querySelector('#admin-graph-canvas');
  if (container) container.innerHTML = renderGraphFallback(view.state.graph);
}

function handleGraphContextLost(view) {
  if (activeView !== view) return;
  view.renderer?.dispose();
  view.renderer = null;
  if (view.contextRecoveryAttempts < 1) {
    view.contextRecoveryAttempts += 1;
    setStatus(view, '3D 표시를 한 번 다시 초기화합니다.');
    renderGraph(view);
    return;
  }
  setStatus(view, '3D 표시를 사용할 수 없어 관계 목록으로 전환했습니다.', true);
  renderFallback(view);
}

export function renderGraphDetail(detail = {}) {
  const aliases = Array.isArray(detail.aliases) ? detail.aliases : [];
  const evidence = Array.isArray(detail.evidence) ? detail.evidence : [];
  const relationCounts = Object.entries(detail.connection_counts || {});
  const relationLabels = { hierarchy: '상하위 관계', related: '연관 관계' };
  const evidenceLabels = evidence.map((item) => {
    const start = item.page_start;
    const end = item.page_end;
    const pages = start === undefined || start === null
      ? ''
      : ` p.${start}${end !== undefined && end !== null && end !== start ? `-${end}` : ''}`;
    return `${escapeHTML(item.doc_short || '문서')}${escapeHTML(pages)}`;
  });
  return `
    <h2>${escapeHTML(detail.label || '선택 개념')}</h2>
    <p class="graph-detail-type">${escapeHTML(detail.node_type || '개념')}</p>
    <dl><dt>연결 수</dt><dd>${escapeHTML(String(detail.degree || 0))}</dd></dl>
    <dl><dt>별칭</dt><dd>${aliases.length ? aliases.map(escapeHTML).join(', ') : '등록된 별칭 없음'}</dd></dl>
    <dl><dt>관계</dt><dd>${relationCounts.length ? relationCounts.map(([type, count]) => `${escapeHTML(relationLabels[type] || type)} ${escapeHTML(String(count))}`).join(', ') : '표시 범위 내 연결 없음'}</dd></dl>
    <dl><dt>근거 위치</dt><dd>${evidenceLabels.length ? evidenceLabels.join(', ') : '등록된 근거 위치 없음'}</dd></dl>`;
}

function renderDetail(view, detail) {
  const panel = view.root.querySelector('#admin-graph-detail');
  if (!panel) return;
  panel.innerHTML = renderGraphDetail(detail);
}

function resizeGraphRenderer() {
  activeView?.renderer?.resize();
}

function setStatus(view, message, isError = false) {
  const status = view.root.querySelector('#admin-graph-status');
  if (!status) return;
  status.textContent = message;
  status.classList.toggle('is-error', isError);
}
