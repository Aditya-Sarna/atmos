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
