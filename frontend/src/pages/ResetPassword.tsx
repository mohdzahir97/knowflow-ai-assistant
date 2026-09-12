/**
 * Landing pages for the two emailed links.
 *
 * Both are reachable while signed in. That is the point for a reset: the case
 * where it matters most is an account someone else also has access to.
 */
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useResetPasswordMutation, useVerifyEmailMutation } from "../api/apiSlice";
import { Alert, Button, ErrorAlert, Field, Icon, Input } from "../components/ui";

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-head">
          <span className="brand-mark" style={{ width: 36, height: 36 }}>
            <Icon name="shield" size={18} />
          </span>
          <h1 style={{ fontSize: "var(--text-lg)" }}>{title}</h1>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [resetPassword, { error, isLoading, isSuccess }] = useResetPasswordMutation();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [mismatch, setMismatch] = useState(false);

  if (!token) {
    return (
      <Shell title="Reset link incomplete">
        <Alert kind="error">
          This link has no token in it. Request a new one from the sign-in screen.
        </Alert>
        <Button block style={{ marginTop: "var(--space-4)" }} onClick={() => navigate("/")}>
          Back to sign in
        </Button>
      </Shell>
    );
  }

  if (isSuccess) {
    return (
      <Shell title="Password updated">
        <Alert kind="success">
          Your password has been changed and all other sessions have been signed out.
        </Alert>
        <Button
          variant="primary"
          block
          style={{ marginTop: "var(--space-4)" }}
          onClick={() => navigate("/")}
        >
          Sign in
        </Button>
      </Shell>
    );
  }

  return (
    <Shell title="Choose a new password">
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          setMismatch(false);
          if (password !== confirmation) {
            setMismatch(true);
            return;
          }
          void resetPassword({ token, new_password: password });
        }}
      >
        <Field label="New password" hint="At least 8 characters, including a letter and a digit.">
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
        <Field label="Confirm new password" error={mismatch ? "The two passwords do not match." : undefined}>
          {(id) => (
            <Input
              id={id}
              type="password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              required
              className={mismatch ? "input-invalid" : undefined}
            />
          )}
        </Field>

        <ErrorAlert error={error} />

        <Button variant="primary" size="lg" block type="submit" loading={isLoading}>
          Set password
        </Button>
      </form>
    </Shell>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";
  const [verifyEmail, { error, isLoading, isSuccess, isUninitialized }] = useVerifyEmailMutation();

  useEffect(() => {
    if (token) void verifyEmail({ token });
  }, [token, verifyEmail]);

  const pending = token !== "" && (isLoading || isUninitialized);

  return (
    <Shell title="Email confirmation">
      {!token && <Alert kind="error">This link has no token in it.</Alert>}
      {pending && (
        <div className="thinking">
          <span className="spinner" />
          Confirming your address...
        </div>
      )}
      {isSuccess && <Alert kind="success">Your email address is confirmed.</Alert>}
      {error && (
        <>
          <ErrorAlert error={error} />
          <p className="muted" style={{ marginTop: "var(--space-2)" }}>
            Sign in and request a new confirmation email from your account page.
          </p>
        </>
      )}
      <Button block style={{ marginTop: "var(--space-4)" }} onClick={() => navigate("/")}>
        Continue
      </Button>
    </Shell>
  );
}
