import type { AuthState } from "../lib/auth";

/** Sign-in screen (Supabase Auth, Google). Shown only when VITE_AUTH_ENABLED=true. */
export function SignIn({ auth }: { auth: AuthState }) {
  return (
    <div className="flex h-full items-center justify-center px-4">
      <div className="card w-full max-w-sm p-6">
        <h1 className="text-xl font-semibold">Synapse</h1>
        <p className="mt-2 text-ink-2">
          Describe a repetitive task. Synapse builds a small specialist for it, tests it against Nemotron, and ships the
          cheapest one that meets your bar.
        </p>
        <button className="btn-primary mt-5 w-full justify-center" disabled={!auth.ready || !!auth.error} onClick={auth.signIn}>
          {auth.ready ? "Continue with Google" : "Loading…"}
        </button>
        {auth.error && <p className="mt-3 text-sm text-danger" role="alert">{auth.error}</p>}
        <p className="mt-4 text-xs text-ink-3">Your specialists, builds and API keys are private to your account. The demo specialists are shared.</p>
      </div>
    </div>
  );
}
