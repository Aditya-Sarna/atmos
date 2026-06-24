import axios from "axios";

export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

export async function authExchange(sessionId) {
  return api.post("/auth/session", { session_id: sessionId });
}

export async function authMe() {
  return api.get("/auth/me");
}

export async function authLogout() {
  return api.post("/auth/logout");
}

export async function listProjects() {
  return api.get("/projects");
}

export async function createProject(payload) {
  return api.post("/projects", payload);
}

export async function updateProjectGithubToken(projectId, githubToken) {
  return api.post(`/projects/${projectId}/github-token`, { github_token: githubToken });
}

export async function getProject(projectId) {
  return api.get(`/projects/${projectId}`);
}

export async function startRun(projectId, command) {
  return api.post(`/projects/${projectId}/runs`, { command });
}

export async function getRun(runId) {
  return api.get(`/runs/${runId}`);
}

export async function listCommands() {
  return api.get("/commands");
}

/**
 * Open a PR on the project's GitHub repo applying a fix.
 * @param {string} runId
 * @param {{ kind: 'issue'|'alt'|'architecture', issue_id?: string, alt_index?: number, suggestion_id?: string, base_branch?: string }} body
 */
export async function applyPatch(runId, body) {
  return api.post(`/runs/${runId}/apply`, body);
}

// ── Swarm load testing ─────────────────────────────────────────────────────
export async function startSwarm(runId, body) {
  return api.post(`/runs/${runId}/swarm/start`, body);
}
export async function getSwarmLive(runId) {
  return api.get(`/runs/${runId}/swarm/live`);
}
export async function generateShipReport(runId) {
  return api.post(`/runs/${runId}/swarm/ship-report`);
}

// ── Payment simulation ─────────────────────────────────────────────────────
export async function simulatePayments(runId, body) {
  return api.post(`/runs/${runId}/payment/simulate`, body);
}
export async function getPaymentResults(runId) {
  return api.get(`/runs/${runId}/payment/results`);
}

// ── GitHub token test ──────────────────────────────────────────────────────
export async function testGithubToken(projectId) {
  return api.post(`/projects/${projectId}/github-token/test`);
}
