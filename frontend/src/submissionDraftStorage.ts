import type { SubmissionDraft } from "./permitState";

export interface DraftScope { userId: string; taskId: string; leaseId: string; expiresAt: string }
const prefix = "cfg-submission-draft:v1:";
const memory = new Map<string, string | null>();
const empty = (): SubmissionDraft => ({ pr_url: "", head_sha: "", summary: "" });
const key = (scope: DraftScope) => prefix + [scope.userId, scope.taskId, scope.leaseId].map(encodeURIComponent).join(":");
const usable = (scope: DraftScope, now: number) =>
  !!scope.userId && !!scope.taskId && !!scope.leaseId && Number.isFinite(now) && Date.parse(scope.expiresAt) > now;
export const hasSubmissionDraft = (draft: SubmissionDraft) => !!(draft.pr_url || draft.head_sha || draft.summary);

function fields(value: unknown): SubmissionDraft | null {
  if (!value || typeof value !== "object") return null;
  const draft = value as Record<string, unknown>;
  if (typeof draft.pr_url !== "string" || draft.pr_url.length > 1000 ||
      typeof draft.head_sha !== "string" || draft.head_sha.length > 64 ||
      typeof draft.summary !== "string" || draft.summary.length > 10000) return null;
  // Select fields explicitly: tokens and permits never enter persistence.
  return { pr_url: draft.pr_url, head_sha: draft.head_sha, summary: draft.summary };
}

export function removeSubmissionDraft(scope: DraftScope) {
  const storageKey = key(scope);
  memory.set(storageKey, null);
  try { globalThis.sessionStorage.removeItem(storageKey); } catch { /* Memory tombstone wins in this page. */ }
}

export function readSubmissionDraft(scope: DraftScope | null, now = Date.now()): SubmissionDraft {
  if (!scope) return empty();
  if (!usable(scope, now)) { removeSubmissionDraft(scope); return empty(); }
  const storageKey = key(scope);
  let raw: string | null | undefined = memory.get(storageKey);
  if (raw === undefined) {
    try { raw = globalThis.sessionStorage.getItem(storageKey); } catch { return empty(); }
  }
  if (!raw) return empty();
  if (raw.length > 80000) { removeSubmissionDraft(scope); return empty(); }
  try {
    const record = JSON.parse(raw);
    const draft = fields(record?.draft);
    if (record?.version !== 1 || record.userId !== scope.userId || record.taskId !== scope.taskId ||
        record.leaseId !== scope.leaseId || !Number.isFinite(record.expiresAt) || record.expiresAt <= now || !draft) {
      removeSubmissionDraft(scope);
      return empty();
    }
    return draft;
  } catch { removeSubmissionDraft(scope); return empty(); }
}

export function writeSubmissionDraft(scope: DraftScope | null, value: SubmissionDraft, now = Date.now()): "persisted" | "memory" {
  if (!scope) return "memory";
  const draft = fields(value);
  if (!usable(scope, now) || !draft || !hasSubmissionDraft(draft)) {
    removeSubmissionDraft(scope);
    return "memory";
  }
  const raw = JSON.stringify({ version: 1, userId: scope.userId, taskId: scope.taskId, leaseId: scope.leaseId,
    expiresAt: Math.min(Date.parse(scope.expiresAt), now + 86400000), draft });
  memory.set(key(scope), raw);
  try { globalThis.sessionStorage.setItem(key(scope), raw); return "persisted"; }
  catch { return "memory"; }
}

export function clearSubmissionDrafts() {
  memory.clear();
  try {
    const storage = globalThis.sessionStorage;
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index++) {
      const candidate = storage.key(index);
      if (candidate?.startsWith(prefix)) keys.push(candidate);
    }
    for (const storageKey of keys) storage.removeItem(storageKey);
  } catch { /* Storage denial must not block logout or identity changes. */ }
}
