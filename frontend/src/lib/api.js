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

export async function authLogin(payload) {
  return api.post("/auth/login", payload);
}

export async function authRegister(payload) {
  return api.post("/auth/register", payload);
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

export async function getProjectCraft(projectId) {
  return api.get(`/projects/${projectId}/craft`);
}

export async function craftGateCheck(projectId, threshold) {
  const q = threshold != null ? `?threshold=${threshold}` : "";
  return api.get(`/projects/${projectId}/craft/gate${q}`);
}

export async function startRun(projectId, body) {
  const payload = typeof body === "string" ? { command: body } : body;
  return api.post(`/projects/${projectId}/runs`, payload);
}

// ── Test plan editor ───────────────────────────────────────────────────────
export async function generateTestPlan(projectId, body) {
  return api.post(`/projects/${projectId}/test-plans/generate`, body);
}
export async function getTestPlan(projectId, planId) {
  return api.get(`/projects/${projectId}/test-plans/${planId}`);
}
export async function updateTestPlan(projectId, planId, body) {
  return api.put(`/projects/${projectId}/test-plans/${planId}`, body);
}
export async function updateProjectSettings(projectId, body) {
  return api.patch(`/projects/${projectId}/settings`, body);
}
export async function listDesignThemes() {
  return api.get("/design-themes");
}

// ── IDE extension ──────────────────────────────────────────────────────────
export async function syncIdeContext(body) {
  return api.post("/ide/context", body);
}
export async function setUserLlmConfig(body) {
  return api.put("/ide/llm-config", body);
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
