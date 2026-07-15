import { API_CONFIG } from '../config.js';
import { fetchAPI } from '../api.js';

function queryString(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : '';
}

export function fetchGraphOverview(options = {}) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_GRAPH_OVERVIEW}${queryString({
    node_limit: options.nodeLimit,
    edge_limit: options.edgeLimit,
  })}`, { signal: options.signal });
}

export function searchGraphNodes(query, options = {}) {
  return fetchAPI(`${API_CONFIG.ENDPOINTS.ADMIN_GRAPH_SEARCH}${queryString({ q: query })}`, {
    signal: options.signal,
  });
}

export function fetchGraphNeighborhood(nodeId, options = {}) {
  const endpoint = API_CONFIG.ENDPOINTS.ADMIN_GRAPH_NODE_BASE
    .replace('{id}', encodeURIComponent(nodeId));
  return fetchAPI(`${endpoint}/neighborhood${queryString({ include_related: options.includeRelated })}`, {
    signal: options.signal,
  });
}

export function fetchGraphNodeDetail(nodeId, options = {}) {
  const endpoint = API_CONFIG.ENDPOINTS.ADMIN_GRAPH_NODE_BASE
    .replace('{id}', encodeURIComponent(nodeId));
  return fetchAPI(endpoint, { signal: options.signal });
}
