export type SessionPhase = "loading" | "error" | "guest" | "authenticated";

export function sessionPhase({ hasData, hasUser, isError }: { hasData: boolean; hasUser: boolean; isError: boolean }): SessionPhase {
  // Keep a known session during background refetches, including failed ones.
  if (hasUser) return "authenticated";
  if (hasData) return "guest";
  return isError ? "error" : "loading";
}
