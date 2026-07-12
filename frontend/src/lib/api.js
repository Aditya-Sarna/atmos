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

// ── Swarm / Chaos Lab ─────────────────────────────────────────────────────
export async function startSwarm(runId, body) {
  return api.post(`/runs/${runId}/swarm/start`, body);
}
export async function startChaos(runId, body) {
  return api.post(`/runs/${runId}/chaos/start`, body);
}
export async function getChaosLive(runId) {
  return api.get(`/runs/${runId}/chaos/live`);
}
export async function setChaosTargets(projectId, body) {
  return api.put(`/projects/${projectId}/chaos/targets`, body);
}
export async function getChaosTargets(projectId) {
  return api.get(`/projects/${projectId}/chaos/targets`);
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

// ── Team / RBAC ──────────────────────────────────────────────────────────────
export async function getTeam() {
  return api.get("/team");
}
export async function updateRolePermissions(roleId, permissions) {
  return api.put(`/team/roles/${roleId}`, { permissions });
}
export async function inviteMember(email, role) {
  return api.post("/team/members", { email, role });
}
export async function updateMemberRole(userId, role) {
  return api.patch(`/team/members/${userId}`, { role });
}
export async function removeMember(userId) {
  return api.delete(`/team/members/${userId}`);
}

// ── Custom test cases ──────────────────────────────────────────────────────
export async function listCustomTestCases(projectId) {
  return api.get(`/projects/${projectId}/test-cases`);
}
export async function createCustomTestCase(projectId, body) {
  return api.post(`/projects/${projectId}/test-cases`, body);
}
export async function updateCustomTestCase(projectId, caseId, body) {
  return api.put(`/projects/${projectId}/test-cases/${caseId}`, body);
}
export async function deleteCustomTestCase(projectId, caseId) {
  return api.delete(`/projects/${projectId}/test-cases/${caseId}`);
}

// ── UI references ────────────────────────────────────────────────────────────
export async function searchReferences(q, appType = "generic") {
  return api.get("/references", { params: { q, app_type: appType } });
}
export async function refreshReferences(appType = "generic") {
  return api.post("/references/refresh", null, { params: { app_type: appType } });
}

// ── Copywriting + Demand intelligence ──────────────────────────────────────
export async function analyzeProjectCopy(projectId) {
  return api.post(`/projects/${projectId}/copywriting/analyze`);
}
export async function rewriteCopy(body) {
  return api.post("/copywriting/rewrite", body);
}
export async function getDemandReport(projectId) {
  return api.post(`/projects/${projectId}/demand/report`);
}
export async function listMarketingProfiles() {
  return api.get("/marketing-profiles");
}
