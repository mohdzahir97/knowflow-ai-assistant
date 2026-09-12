/** Sign in, create an account, and request a password reset. */
import { useState } from "react";

import { useForgotPasswordMutation, useRegisterMutation } from "../api/apiSlice";
import { useSession } from "../store/session";
import { Alert, Button, ErrorAlert, Field, Icon, Input, Tabs } from "../components/ui";

const TABS = ["Sign in", "Create account"] as const;
type Tab = (typeof TABS)[number];

export default function SignIn() {
  const [tab, setTab] = useState<Tab>("Sign in");

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-head">
          <span className="brand-mark" style={{ width: 36, height: 36 }}>
            <Icon name="sparkles" size={18} />
          </span>
          <h1 style={{ fontSize: "var(--text-xl)" }}>Knowledge Assistant</h1>
          <p className="muted">Ask questions about your organisation's knowledge base.</p>
        </div>

        <Tabs tabs={TABS} active={tab} onChange={setTab} />
        {tab === "Sign in" ? <LoginForm /> : <RegisterForm onDone={() => setTab("Sign in")} />}
      </div>
    </div>
  );
}

function LoginForm() {
  const { signIn } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <form onSubmit={submit} className="stack">
        <Field label="Email">
          {(id) => (
            <Input
              id={id}
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          )}
        </Field>
        <Field label="Password">
          {(id) => (
            <Input
              id={id}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          )}
        </Field>

        <ErrorAlert error={error} />

        <Button variant="primary" size="lg" block type="submit" loading={busy}>
          Sign in
        </Button>
      </form>
      <ForgotPassword />
    </>
  );
}

function RegisterForm({ onDone }: { onDone: () => void }) {
  const [register, { error, isLoading }] = useRegisterMutation();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await register({ email, password, full_name: fullName || null }).unwrap();
      setDone(true);
      onDone();
    } catch {
      /* shown inline */
    }
  };

  if (done) return <Alert kind="success">Account created. You can sign in now.</Alert>;

  return (
    <form onSubmit={submit} className="stack">
      <Field label="Full name (optional)">
        {(id) => (
          <Input id={id} value={fullName} onChange={(event) => setFullName(event.target.value)} />
        )}
      </Field>
      <Field label="Email">
        {(id) => (
          <Input
            id={id}
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        )}
      </Field>
      <Field label="Password" hint="At least 8 characters, including a letter and a digit.">
        {(id) => (
          <Input
            id={id}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        )}
      </Field>

      <ErrorAlert error={error} />

      <Button variant="primary" size="lg" block type="submit" loading={isLoading}>
        Create account
      </Button>
    </form>
  );
}

function ForgotPassword() {
  const [forgotPassword, { error, isLoading, isSuccess }] = useForgotPasswordMutation();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");

  if (!open) {
    return (
      <div style={{ marginTop: "var(--space-4)", textAlign: "center" }}>
        <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
          Forgotten your password?
        </Button>
      </div>
    );
  }

  return (
    <form
      className="stack"
      style={{ marginTop: "var(--space-5)" }}
      onSubmit={(event) => {
        event.preventDefault();
        void forgotPassword({ email });
      }}
    >
      <hr />
      <Field label="Email" hint="We will send a reset link if the address has an account.">
        {(id) => (
          <Input
            id={id}
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        )}
      </Field>

      <ErrorAlert error={error} />
      {/* Deliberately unconditional: confirming whether the address exists
          would turn this into a membership oracle. */}
      {isSuccess && (
        <Alert kind="success">If that address has an account, a reset link has been sent.</Alert>
      )}

      <div className="row">
        <Button type="submit" loading={isLoading}>
          Email me a reset link
        </Button>
        <Button variant="ghost" type="button" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
