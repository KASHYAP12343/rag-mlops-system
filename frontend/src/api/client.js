/**
 * API client for the RAG backend.
 * All endpoints proxy through Vite dev server → localhost:8000
 *
 * Supports only the advanced (multi-query + reranking) endpoints.
 */

const BASE = '/api/v1';

async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.message || `Request failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Send a query — uses /advanced_query.
 */
export async function sendQuery(question, sessionId = null) {
  const payload = { question, session_id: sessionId ?? null };
  console.debug('[api] sendQuery payload ->', payload);
  return await request(`${BASE}/advanced_query`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Send a debug query — uses /advanced_query_debug.
 */
export async function sendDebugQuery(question, sessionId = null) {
  const payload = { question, session_id: sessionId ?? null };
  console.debug('[api] sendDebugQuery payload ->', payload);
  return await request(`${BASE}/advanced_query_debug`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Clear conversation history for a specific session.
 */
export async function clearSession(sessionId) {
  return request(`${BASE}/session/${sessionId}`, { method: 'DELETE' });
}

/**
 * Check backend health status.
 */
export async function checkHealth() {
  return request(`${BASE}/health`);
}

/**
 * Get collection stats.
 */
export async function getStats() {
  return request(`${BASE}/stats`);
}
