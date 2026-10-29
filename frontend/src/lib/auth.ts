import { useEffect, useState } from "react";
import type { Session, SupabaseClient } from "@supabase/supabase-js";
import { setTokenGetter } from "./api";

/** Sign-in with Supabase Auth (Google), behind VITE_AUTH_ENABLED. Off: no login screen, calls go without a token
 * (local dev, replay; the backend lets them through while AUTH_REQUIRED=false). */
export const AUTH_ENABLED = String(import.meta.env.VITE_AUTH_ENABLED ?? "").toLowerCase() === "true";
const URL_ = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const ANON = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

let client: SupabaseClient | null = null;
async function supabase(): Promise<SupabaseClient | null> {
  if (!AUTH_ENABLED || !URL_ || !ANON) return null;
  if (!client) {
    const { createClient } = await import("@supabase/supabase-js");     // loaded only when sign-in is on
    client = createClient(URL_, ANON, { auth: { persistSession: true, autoRefreshToken: true } });
    setTokenGetter(async () => (await client!.auth.getSession()).data.session?.access_token ?? null);
  }
  return client;
}

export type AuthState = { enabled: boolean; ready: boolean; session: Session | null; error: string;
                          signIn: () => Promise<void>; signOut: () => Promise<void> };

export function useAuth(): AuthState {
  const [ready, setReady] = useState(!AUTH_ENABLED);
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!AUTH_ENABLED) return;
    if (!URL_ || !ANON) { setError("Sign-in is on but VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY is missing."); setReady(true); return; }
    let unsub = () => {};
    supabase().then((sb) => {
      if (!sb) return;
      sb.auth.getSession().then(({ data }) => { setSession(data.session); setReady(true); });
      unsub = sb.auth.onAuthStateChange((_e, s) => setSession(s)).data.subscription.unsubscribe;
    });
    return () => unsub();
  }, []);
  return {
    enabled: AUTH_ENABLED, ready, session, error,
    signIn: async () => {
      const sb = await supabase();
      if (!sb) return;
      const { error: e } = await sb.auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });
      if (e) setError(e.message);
    },
    signOut: async () => { await (await supabase())?.auth.signOut(); },
  };
}
