export interface SubmissionPermit { token: string; expires_at: string }
export interface SubmissionDraft { pr_url: string; head_sha: string; summary: string }
export interface PermitState { permit: SubmissionPermit | null; draft: SubmissionDraft; invalidated: boolean }
export type PermitAction =
  | { type: "issued"; permit: SubmissionPermit }
  | { type: "invalidated" }
  | { type: "edit"; field: keyof SubmissionDraft; value: string };

export function initialPermitState(): PermitState {
  return { permit: null, draft: { pr_url: "", head_sha: "", summary: "" }, invalidated: false };
}

export function permitReducer(state: PermitState, action: PermitAction): PermitState {
  return action.type === "invalidated" ? { ...state, invalidated: true } : action.type === "issued"
    ? { ...state, permit: action.permit, invalidated: false }
    : { ...state, draft: { ...state.draft, [action.field]: action.value } };
}

export function permitIsValid(permit: SubmissionPermit | null, now: number): boolean {
  return !!permit?.token && Number.isFinite(now) && Date.parse(permit.expires_at) > now;
}

export function leaseIsUsable(lease: { status: string; expires_at: string; token?: string }, now: number): boolean {
  return lease.status === "ACTIVE" && !!lease.token && Number.isFinite(now) && Date.parse(lease.expires_at) > now;
}

export function submissionPayload(state: PermitState, now: number, lease: { status: string; expires_at: string; token?: string }) {
  if (state.invalidated || !permitIsValid(state.permit, now) || !leaseIsUsable(lease, now)) return null;
  return { ...state.draft, permit_token: state.permit!.token };
}
