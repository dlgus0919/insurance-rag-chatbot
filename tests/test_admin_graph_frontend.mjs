import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  activateAdminGraphPage,
  deactivateAdminGraphPage,
  GraphPageState,
  normalizeGraphPayload,
  renderGraphDetail,
  renderGraphFallback,
} from '../frontend/js/pages/admin-graph.js';
import { cameraPositionForNode, createGraphRenderer } from '../frontend/js/graph/renderer-3d.js';

function makeFakeGraph(calls) {
  const graph = {};
  const chain = [
    'backgroundColor', 'nodeId', 'nodeLabel', 'nodeAutoColorBy', 'nodeVal',
    'linkSource', 'linkTarget', 'linkOpacity', 'linkWidth', 'cooldownTime',
    'warmupTicks', 'enableNodeDrag', 'graphData', 'width', 'height',
  ];
  chain.forEach((name) => {
    graph[name] = (...args) => {
      calls.push(`${name}:${args[0] ?? ''}`);
      return graph;
    };
  });
  graph.renderer = () => ({ setPixelRatio: (value) => calls.push(`pixelRatio:${value}`) });
  graph.onNodeClick = (handler) => {
    calls.push(handler ? 'onNodeClick:set' : 'onNodeClick:clear');
    graph.clickHandler = handler;
    return graph;
  };
  graph.pauseAnimation = () => calls.push('pauseAnimation');
  graph.resumeAnimation = () => calls.push('resumeAnimation');
  graph.cameraPosition = () => calls.push('cameraPosition');
  graph._destructor = () => calls.push('destructor');
  return graph;
}

function makeFakeContainer() {
  return {
    clientWidth: 800,
    clientHeight: 500,
    querySelector: () => null,
    replaceChildren() {},
  };
}

test('graph payload stays bounded before rendering', () => {
  const payload = {
    nodes: Array.from({ length: 300 }, (_, index) => ({
      id: `node-${index}`,
      label: `노드 ${index}`,
      node_type: 'Document',
      degree: 0,
      score: 0,
      confidence: 1,
    })),
    edges: Array.from({ length: 600 }, (_, index) => ({
      id: `edge-${index}`,
      source: 'node-0',
      target: `node-${index + 1}`,
      edge_type: 'RELATED',
      semantic_role: 'related',
    })),
  };

  const normalized = normalizeGraphPayload(payload, { nodeLimit: 250, edgeLimit: 500 });

  assert.equal(normalized.nodes.length, 250);
  assert.equal(normalized.edges.length, 249);
});

test('graph payload uses the approved overview defaults', () => {
  const payload = {
    nodes: Array.from({ length: 200 }, (_, index) => ({
      id: `node-${index}`,
      label: `노드 ${index}`,
      node_type: 'Document',
      degree: 0,
      score: 0,
      confidence: 1,
    })),
    edges: Array.from({ length: 300 }, (_, index) => ({
      id: `edge-${index}`,
      source: `node-${index % 120}`,
      target: `node-${(index + 1) % 120}`,
      edge_type: 'RELATED',
      semantic_role: 'related',
    })),
  };

  const normalized = normalizeGraphPayload(payload);

  assert.equal(normalized.nodes.length, 120);
  assert.equal(normalized.edges.length, 240);
});

test('graph state resets the selected node when returning to overview', () => {
  const state = new GraphPageState();
  state.selectNode('node-1');
  state.setGraph({ nodes: [], edges: [] }, 'focus');
  state.resetOverview();

  assert.equal(state.selectedNodeId, null);
  assert.equal(state.mode, 'overview');
});

test('graph page exposes explicit activation lifecycle hooks', () => {
  assert.equal(typeof activateAdminGraphPage, 'function');
  assert.equal(typeof deactivateAdminGraphPage, 'function');
});

test('2d fallback escapes labels and distinguishes hierarchy edges', () => {
  const html = renderGraphFallback({
    nodes: [
      { id: 'root', label: '<script>alert(1)</script>', node_type: 'ClaimCondition', degree: 2 },
      { id: 'child', label: '하위 개념', node_type: 'CoverageItem', degree: 1 },
    ],
    edges: [{ id: 'edge-1', source: 'root', target: 'child', edge_type: 'HAS_CATEGORY', semantic_role: 'child' }],
  });

  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>alert/);
  assert.match(html, /하위/);
  assert.match(html, /data-graph-node-id="root"/);
});

test('detail panel renders the safe source label and bounded page range', () => {
  const html = renderGraphDetail({
    label: '수술 A',
    node_type: 'SurgeryProcedure',
    degree: 2,
    aliases: ['수술가'],
    connection_counts: { hierarchy: 1, related: 1 },
    evidence: [{ doc_short: '약관', page_start: 10, page_end: 11 }],
  });

  assert.match(html, /약관/);
  assert.match(html, /p\.10-11/);
  assert.doesNotMatch(html, /undefined/);
});

test('3d node focus computes a finite camera position outside the node', () => {
  const position = cameraPositionForNode({ x: 10, y: -4, z: 3 }, 80);

  assert.ok(Number.isFinite(position.x));
  assert.ok(Number.isFinite(position.y));
  assert.ok(Number.isFinite(position.z));
  assert.ok(Math.hypot(position.x - 10, position.y + 4, position.z - 3) > 0);
});

test('renderer enforces cooldown and releases resources on disposal', () => {
  const calls = [];
  const graph = makeFakeGraph(calls);
  const controller = createGraphRenderer(makeFakeContainer(), {
    graphFactory: () => graph,
    cooldownMs: 1200,
    pixelRatioCap: 1.25,
  });

  controller.setGraph({ nodes: [], edges: [] });
  controller.pause();
  controller.dispose();

  assert.ok(calls.includes('cooldownTime:1200'));
  assert.ok(calls.includes('pixelRatio:1'));
  assert.ok(calls.includes('pauseAnimation'));
  assert.ok(calls.includes('onNodeClick:clear'));
  assert.ok(calls.includes('destructor'));
});

test('GraphDB page uses a self-hosted bundle rather than a CDN', async () => {
  const [indexHtml, packageJson, configJs] = await Promise.all([
    readFile(new URL('../frontend/index.html', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/package.json', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/js/config.js', import.meta.url), 'utf8'),
  ]);

  assert.match(indexHtml, /\/dist\/graph-viz\.min\.js/);
  assert.doesNotMatch(indexHtml, /https:\/\/.*(three|force-graph)/i);
  assert.match(packageJson, /"build:graph"/);
  assert.match(configJs, /ADMIN_GRAPH_OVERVIEW/);
  assert.match(configJs, /\/admin\/graph\/overview/);
});
