import { getLocale } from "./i18n";

export interface User {
  id: string;
  username: string;
  role: string;
  token?: string;
}
export interface AuthSession {
  user: User | null;
  csrf_token: string | null;
  github_available?: boolean;
}
export interface Credential {
  id: string;
  name: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  revoked_at?: string | null;
  last_used_at?: string | null;
  token?: string;
}
export interface Project {
  id: string;
  slug: string;
  name: string;
  description: string;
  repository_url: string;
  language: string;
  status: string;
  impact_score: number;
  readiness_score: number;
  is_demo: boolean;
  required_checks?: string[];
  maintainer_id?: string | null;
}
export interface Lease {
  id: string;
  task_id: string;
  user_id: string;
  expires_at: string;
  status: string;
  token?: string;
}
export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  difficulty: string;
  risk: string;
  required_model_tier: string;
  estimated_minutes: number;
  status: string;
  acceptance_criteria: string[];
  allowed_paths: string[];
  forbidden_paths: string[];
  verification_commands: string[];
  active_lease?: Lease | null;
  is_demo: boolean;
  version?: number;
  improvement_id?: string | null;
  contract_locked?: boolean;
}
export interface Finding {
  severity: string;
  description: string;
}
export interface Review {
  id: string;
  submission_id: string;
  reviewer_id: string;
  head_sha: string;
  decision: string;
  summary: string;
  findings: Finding[];
  created_at: string;
  is_current: boolean;
}
export interface Submission {
  id: string;
  task_id: string;
  author_id: string;
  pr_url: string;
  head_sha: string;
  status: string;
  created_at: string;
  quorum: {
    required: number;
    approved: number;
    blocked: boolean;
    passed: boolean;
    human_required: boolean;
    blind?: boolean;
    reviews_completed?: number;
  };
  reviews?: Review[];
  is_demo: boolean;
}
export interface Event {
  id: string;
  kind: string;
  entity_id: string;
  message: string;
  created_at: string;
}
export interface Activity {
  leases: Lease[];
  submissions: Submission[];
  reviews: Review[];
  events: Event[];
}
export interface Stats {
  projects: number;
  tasks_available: number;
  submissions: number;
  reviews: number;
  merged: number;
  demo_mode: boolean;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
let token: string | undefined;
let csrfToken: string | undefined;
export function setToken(value?: string) {
  token = value;
}
export function setCsrfToken(value?: string | null) {
  csrfToken = value ?? undefined;
}
export async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const response = await fetch("/api" + path, {
    credentials: "include",
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers: {
      "Content-Type": "application/json",
      "Accept-Language": getLocale(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(csrfToken &&
      !token &&
      (method ?? (body === undefined ? "GET" : "POST")) !== "GET"
        ? { "X-CSRF-Token": csrfToken }
        : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    let message = "Request failed ({status})";
    try {
      const data = await response.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail ?? data);
    } catch {
      /* response may be empty */
    }
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? (null as T) : response.json();
}
