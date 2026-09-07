const API_BASE = "http://127.0.0.1:18137";

export type LocalResult = { ok: boolean; cancelled?: boolean; paths?: string[]; path?: string; error?: string };
export type Job = {
  id: string;
  stepId: string;
  actionId: string;
  status: string;
  completed: number;
  total: number;
  allowedAction?: "resume" | "restart";
  outputs?: Record<string, string>;
};
export type StepResult = {
  ok: boolean;
  stepId: string;
  status: string;
  message: string;
  outputs: string[];
  jobId?: string;
  code?: string;
  retryable?: boolean;
  data?: Record<string, unknown>;
};
export type Workspace = {
  product: string;
  mode: string;
  currentTask: string | null;
  workflowVersion: number | null;
  workflowReadOnly: boolean;
  steps: Array<{ id: string; number: string; title: string; runner: string; status: string }>;
};

export type AutomationBridge = {
  workerSessionSecret: () => string;
  selectNewTaskParentDirectory: () => Promise<string | null>;
  selectTaskDirectory: () => Promise<string | null>;
  openAsinWorkbook: (taskDir: string) => Promise<LocalResult>;
  selectInput: (kind: "pomelo" | "pomeloKeywords", taskDir: string) => Promise<LocalResult>;
  openOutput: (kind: "pomelo" | "wheat" | "pomeloKeywords", taskDir: string) => Promise<LocalResult>;
  saveCurl: (kind: "wheat" | "pomeloKeywords", taskDir: string, content: string) => Promise<LocalResult>;
  launchDebugChrome: () => Promise<LocalResult>;
  stopJob: (jobId: string) => Promise<StepResult>;
  resumeJob: (jobId: string) => Promise<StepResult>;
  restartJob: (jobId: string) => Promise<StepResult>;
};

declare global {
  interface Window {
    automationTool?: AutomationBridge;
  }
}

export class WorkerError extends Error {
  constructor(public readonly code: string, message: string) {
    super(message || code);
  }
}

function headers(json = false): HeadersInit {
  const result: Record<string, string> = {
    "X-Data-Automation-Session": window.automationTool?.workerSessionSecret() || "",
  };
  if (json) result["Content-Type"] = "application/json";
  return result;
}

async function read<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new WorkerError(payload.code || payload.error || "worker_error", payload.message || "本地服务请求失败");
  return payload as T;
}

export async function get<T>(path: string): Promise<T> {
  return read<T>(await fetch(`${API_BASE}${path}`, { headers: headers() }));
}

export async function post<T>(path: string, payload: unknown): Promise<T> {
  return read<T>(await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify(payload),
  }));
}

export const fetchWorkspace = () => get<Workspace>("/api/workspace");
export const createTask = (taskName: string, parentDir: string) => post<{ currentTask: string }>("/api/task/create", { taskName, parentDir });
export const selectTask = (taskDir: string) => post<{ currentTask: string }>("/api/task/select", { taskDir });
export const runAction = (stepId: string, actionId: string, payload: Record<string, unknown> = {}) =>
  post<StepResult>(`/api/steps/${stepId}/run`, { ...payload, actionId });
export const fetchJobs = () => get<{ items: Job[] }>("/api/jobs/resumable");
