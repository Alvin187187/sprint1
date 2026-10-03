import { useState } from "react";

import { useSession } from "../state/session";
import { Button, Field, SkipLink, ThemeToggle, inputClass } from "../components/ui";

export function LoginPage() {
  const { signIn } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch {
      setError("Email or password is incorrect. Check both and try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full grid md:grid-cols-[minmax(0,1.1fr)_minmax(22rem,28rem)]">
      <SkipLink />
      <aside className="hidden md:flex flex-col justify-between bg-[var(--color-surface)] px-10 py-10 border-r border-[var(--color-border)]">
        <p className="font-display text-[40px] leading-[1.12] text-[var(--color-fg)] anim-in">
          Career
          <br />
          Transition
          <br />
          Advisor
        </p>
        <p className="text-[16px] text-[var(--color-fg-muted)] max-w-[22rem] leading-relaxed">
          Mentoring for Eskwelabs learners moving into data roles in the Philippines.
        </p>
      </aside>

      <div className="flex flex-col min-h-0 bg-[var(--color-bg)]">
        <header className="h-14 flex items-center justify-between px-4 md:justify-end">
          <p className="md:hidden font-display text-[22px] leading-none">Advisor</p>
          <ThemeToggle />
        </header>
        <main id="main" className="flex-1 flex items-center px-5 pb-10">
          <div className="w-full max-w-md mx-auto anim-in">
            <h1 className="text-[32px] leading-none">Sign in</h1>
            <p className="mt-2 mb-6 text-[16px] text-[var(--color-fg-muted)]">
              Use the account an admin created for you.
            </p>
            <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
              <Field label="Email" htmlFor="email">
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="username"
                  spellCheck={false}
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className={inputClass}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? "login-error" : undefined}
                />
              </Field>
              <Field label="Password" htmlFor="password">
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className={inputClass}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? "login-error" : undefined}
                />
              </Field>
              {error && (
                <p id="login-error" role="alert" className="text-[15px] text-[var(--color-danger-fg)]">
                  {error}
                </p>
              )}
              <Button type="submit" variant="primary" disabled={busy} className="w-full">
                {busy ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          </div>
        </main>
      </div>
    </div>
  );
}
