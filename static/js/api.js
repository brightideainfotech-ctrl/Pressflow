// Shared app state and the fetch wrapper. All server errors become ApiError with a readable message.

const KEY = "press.token";

export const state = { user: null, settings: {}, stages: [], myStages: [], masters: {} };

export function getToken() {
  try { return localStorage.getItem(KEY) || ""; } catch { return ""; }
}
export function setToken(t) {
  try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch { /* private mode: stay signed in for this page only */ }
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = "Bearer " + token;
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check the network connection and try again.");
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    if (res.status === 401 && token && path !== "/api/login") window.dispatchEvent(new Event("press:signed-out"));
    throw new ApiError(res.status, (data && data.error) || `Request failed (${res.status})`);
  }
  return data;
}

export const get = (p) => api("GET", p);
export const post = (p, b = {}) => api("POST", p, b);
export const put = (p, b = {}) => api("PUT", p, b);
export const del = (p) => api("DELETE", p);

export async function loadBootstrap() {
  const b = await get("/api/bootstrap");
  state.user = b.user;
  state.settings = b.settings;
  state.stages = b.stages;
  state.myStages = b.my_stages;
  state.masters = b.masters;
  return b;
}

export const isOffice = () => state.user && (state.user.role === "manager" || state.user.role === "desk");
export const isManager = () => state.user && state.user.role === "manager";
export const stageLabel = (key) => (state.stages.find((s) => s.key === key) || { label: key }).label;
