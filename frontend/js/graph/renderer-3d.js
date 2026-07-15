const DEFAULTS = Object.freeze({
  cooldownMs: 1200,
  pixelRatioCap: 1.25,
  cameraDurationMs: 650,
  backgroundColor: '#081426',
});

function escapeGraphLabel(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[character]));
}

export function canUseWebGL() {
  if (typeof document === 'undefined') return false;
  const canvas = document.createElement('canvas');
  return Boolean(canvas.getContext('webgl') || canvas.getContext('experimental-webgl'));
}

export function cameraPositionForNode(node = {}, distance = 90) {
  const x = Number(node.x) || 0;
  const y = Number(node.y) || 0;
  const z = Number(node.z) || 0;
  const length = Math.hypot(x, y, z);
  if (!length) return { x: 0, y: 0, z: distance };
  const ratio = 1 + distance / length;
  return { x: x * ratio, y: y * ratio, z: z * ratio };
}

function instantiateGraph(graphFactory, container) {
  const candidate = graphFactory();
  return typeof candidate === 'function' ? candidate(container) : candidate;
}

export function createGraphRenderer(container, options = {}) {
  const config = { ...DEFAULTS, ...options };
  const graphFactory = options.graphFactory
    || globalThis.InsuranceGraph3D
    || globalThis.InsuranceGraphForce3D;
  if (!graphFactory || (!options.graphFactory && !canUseWebGL())) return null;

  const graph = instantiateGraph(graphFactory, container)
    .backgroundColor(config.backgroundColor)
    .nodeId('id')
    .nodeLabel((node) => `<strong>${escapeGraphLabel(node.label)}</strong><br>${escapeGraphLabel(node.node_type)}`)
    .nodeAutoColorBy('node_type')
    .nodeVal((node) => Math.min(12, 2 + Math.sqrt(node.degree || 0)))
    .linkSource('source')
    .linkTarget('target')
    .linkOpacity(0.28)
    .linkWidth((edge) => (edge.semantic_role === 'overview' ? 1.2 : 1.8))
    .cooldownTime(config.cooldownMs)
    .warmupTicks(30)
    .enableNodeDrag(false);

  graph.renderer?.().setPixelRatio?.(
    Math.min(Number(globalThis.devicePixelRatio) || 1, config.pixelRatioCap),
  );

  let disposed = false;
  let pauseTimer = null;
  let canvas = null;
  let clickHandler = null;

  function handleContextLost(event) {
    event.preventDefault();
    config.onContextLost?.();
  }

  function attachContextListener() {
    const nextCanvas = container.querySelector?.('canvas') || null;
    if (nextCanvas === canvas) return;
    canvas?.removeEventListener('webglcontextlost', handleContextLost);
    canvas = nextCanvas;
    canvas?.addEventListener('webglcontextlost', handleContextLost);
  }

  function schedulePause(delay = config.cooldownMs + 50) {
    clearTimeout(pauseTimer);
    pauseTimer = globalThis.setTimeout(() => {
      if (!disposed) graph.pauseAnimation?.();
    }, delay);
  }

  const controller = {
    setGraph(payload) {
      if (disposed) return;
      graph.graphData({ nodes: payload.nodes, links: payload.edges });
      attachContextListener();
      schedulePause();
    },
    focusNode(node) {
      if (disposed || !node) return;
      graph.resumeAnimation?.();
      graph.cameraPosition?.(
        cameraPositionForNode(node),
        node,
        config.cameraDurationMs,
      );
      schedulePause(config.cameraDurationMs + 50);
    },
    onNodeClick(handler) {
      clickHandler = typeof handler === 'function' ? handler : null;
      graph.onNodeClick(clickHandler ? (node) => {
        controller.focusNode(node);
        clickHandler(node);
      } : null);
    },
    pause() {
      clearTimeout(pauseTimer);
      graph.pauseAnimation?.();
    },
    resume() {
      if (!disposed) graph.resumeAnimation?.();
    },
    resize() {
      if (disposed) return;
      graph.width?.(container.clientWidth).height?.(container.clientHeight);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      clearTimeout(pauseTimer);
      canvas?.removeEventListener('webglcontextlost', handleContextLost);
      canvas = null;
      graph.onNodeClick?.(null);
      graph.pauseAnimation?.();
      graph._destructor?.();
      container.replaceChildren();
    },
  };

  controller.onNodeClick(config.onNodeClick);
  return controller;
}
