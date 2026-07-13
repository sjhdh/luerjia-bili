import type { AuthSession, BrowserSession, Job, ReportPayload, ShareLink } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) }
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || "请求失败");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  authSession: () => request<AuthSession>("/api/v1/auth/session"),
  login: (username: string, password: string) =>
    request<AuthSession>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    }),
  logout: () => request<AuthSession>("/api/v1/auth/logout", { method: "POST" }),
  jobs: () => request<Job[]>("/api/v1/jobs"),
  job: (id: string) => request<Job>(`/api/v1/jobs/${id}`),
  createJob: (payload: Record<string, unknown>) =>
    request<Job>("/api/v1/jobs", { method: "POST", body: JSON.stringify(payload) }),
  cancelJob: (id: string) => request<Job>(`/api/v1/jobs/${id}/cancel`, { method: "POST" }),
  retryJob: (id: string) => request<Job>(`/api/v1/jobs/${id}/retry`, { method: "POST" }),
  rerunJob: (id: string) => request<Job>(`/api/v1/jobs/${id}/rerun`, { method: "POST" }),
  selectTapTap: (id: string, appId: string) =>
    request<Job>(`/api/v1/jobs/${id}/taptap-selection`, {
      method: "POST",
      body: JSON.stringify({ app_id: appId })
    }),
  platformSession: (platform: BrowserSession["platform"]) =>
    request<BrowserSession>(`/api/v1/platforms/${platform}/session`),
  openWorkspace: (platform: BrowserSession["platform"]) =>
    request<BrowserSession>(`/api/v1/platforms/${platform}/workspace`, { method: "POST" }),
  disconnectPlatform: (platform: BrowserSession["platform"]) =>
    request<BrowserSession>(`/api/v1/platforms/${platform}/session`, { method: "DELETE" }),
  browserInput: (platform: BrowserSession["platform"], payload: Record<string, unknown>) =>
    request<BrowserSession>(`/api/v1/platforms/${platform}/input`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  report: (id: string) => request<ReportPayload>(`/api/v1/reports/${id}`),
  sharedReport: (token: string) => request<ReportPayload>(`/api/v1/shared/reports/${token}`),
  createShare: (id: string, expiresInDays = 7) =>
    request<ShareLink>(`/api/v1/reports/${id}/shares`, {
      method: "POST",
      body: JSON.stringify({ expires_in_days: expiresInDays })
    })
};
