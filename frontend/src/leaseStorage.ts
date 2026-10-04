// Storage may be denied by browser policy or full. Keep a newly acquired token
// in memory before persisting so a storage exception cannot lose the claim.
const memory = new Map<string, string>();
type Store = "localStorage" | "sessionStorage";

export function writeLeaseToken(store: Store, key: string, token: string) {
  memory.set(`${store}:${key}`, token);
  try {
    globalThis[store].setItem(key, token);
  } catch {
    // Memory remains usable for the current page lifetime.
  }
}

export function readLeaseToken(store: Store, key: string): string | undefined {
  const current = memory.get(`${store}:${key}`);
  if (current !== undefined) return current;
  try {
    return globalThis[store].getItem(key) ?? undefined;
  } catch {
    return undefined;
  }
}
