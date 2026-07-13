import type { BrowserSession, Job, ReportPayload } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) }
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || "请求失败");
  }
  return response.json() as Promise<T>;
}

export const api = {
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
  session: () => request<BrowserSession>("/api/v1/bilibili/session"),
  connect: () => request<BrowserSession>("/api/v1/bilibili/login-window", { method: "POST" }),
  disconnect: () => request<BrowserSession>("/api/v1/bilibili/session", { method: "DELETE" }),
  report: (id: string) => request<ReportPayload>(`/api/v1/reports/${id}`)
};
