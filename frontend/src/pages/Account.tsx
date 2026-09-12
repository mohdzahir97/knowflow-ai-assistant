/**
 * The signed-in user's own account.
 *
 * Sign-in history is shown to the user themselves rather than only to an
 * administrator, because the person best placed to notice an unfamiliar
 * sign-in is the account's owner.
 */
import { useGetLoginHistoryQuery, useResendVerificationMutation } from "../api/apiSlice";
import { useAppDispatch } from "../store/hooks";
import { useSession } from "../store/session";
import { toastRaised } from "../store/uiSlice";
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorAlert,
  Icon,
  SkeletonRows,
  Timestamp,
} from "../components/ui";

const ACTION_LABELS: Record<string, string> = {
  "login.succeeded": "Signed in",
  "login.failed": "Failed sign-in attempt",
  logout: "Signed out",
  "user.password_reset": "Password reset",
};

export default function Account() {
  const dispatch = useAppDispatch();
  const { profile, isAdmin } = useSession();
  const { data: events, error, isLoading } = useGetLoginHistoryQuery();
  const [resend, resendState] = useResendVerificationMutation();

  const failures = events?.filter((event) => event.action === "login.failed").length ?? 0;

  const sendConfirmation = async () => {
    try {
      await resend().unwrap();
      dispatch(toastRaised("success", "Confirmation email sent."));
    } catch {
      /* shown inline */
    }
  };

  return (
    <div className="content stack">
      <div className="page-header">
        <div className="row">
          <span className="avatar avatar-lg" aria-hidden="true">
            {(profile?.email ?? "?").slice(0, 1)}
          </span>
          <div>
            <h2>{profile?.full_name || profile?.email}</h2>
            <div className="row-wrap" style={{ marginTop: "var(--space-1)" }}>
              <span className="muted">{profile?.email}</span>
              {isAdmin && (
                <Badge tone="accent" icon="shield">
                  Administrator
                </Badge>
              )}
              {profile?.is_verified ? (
                <Badge tone="success" icon="check">
                  Verified
                </Badge>
              ) : (
                <Badge tone="warning" icon="warning">
                  Unverified
                </Badge>
              )}
            </div>
          </div>
        </div>
      </div>

      <Card title="Email address">
        {profile?.is_verified ? (
          <Alert kind="success">Your email address is confirmed.</Alert>
        ) : (
          <div className="stack-sm">
            <Alert kind="info">
              Your email address has not been confirmed yet. Confirming it means password reset
              links can reach you.
            </Alert>
            <ErrorAlert error={resendState.error} />
            <div>
              <Button icon="send" loading={resendState.isLoading} onClick={sendConfirmation}>
                Send confirmation email
              </Button>
            </div>
          </div>
        )}
      </Card>

      <Card
        title="Recent sign-in activity"
        subtitle="If you see something you do not recognise, change your password."
      >
        <div className="stack-sm">
          {failures > 0 && (
            <Alert kind="warning">
              {failures} failed sign-in attempt{failures === 1 ? "" : "s"} in your recent history.
            </Alert>
          )}
          <ErrorAlert error={error} />

          {isLoading ? (
            <SkeletonRows rows={4} />
          ) : (events ?? []).length === 0 ? (
            <p className="muted">No activity recorded yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Event</th>
                    <th>IP address</th>
                  </tr>
                </thead>
                <tbody>
                  {(events ?? []).map((event, index) => (
                    <tr key={index}>
                      <td className="cell-nowrap">
                        <Timestamp value={event.created_at} relative />
                      </td>
                      <td>
                        <span className="row" style={{ gap: "var(--space-2)" }}>
                          {event.action === "login.failed" && (
                            <Icon
                              name="warning"
                              size={13}
                              style={{ color: "var(--warning)", flex: "0 0 auto" }}
                            />
                          )}
                          {ACTION_LABELS[event.action] ?? event.action}
                        </span>
                      </td>
                      <td className="cell-nowrap">{event.ip_address ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
