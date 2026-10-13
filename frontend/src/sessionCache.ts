import type { QueryClient } from "@tanstack/react-query";
import { setCsrfToken, type AuthSession } from "./api";

export async function resetSessionQueries(client: QueryClient) {
  // Stop old responses before they can repopulate caches under a new identity.
  await client.cancelQueries();
  client.removeQueries({ predicate: query =>
    !["auth-session", "health", "demo-users"].includes(String(query.queryKey[0])) });
}

export async function replaceAuthSession(client: QueryClient, session: AuthSession) {
  await resetSessionQueries(client);
  setCsrfToken(session.csrf_token);
  client.setQueryData(["auth-session"], session);
}
