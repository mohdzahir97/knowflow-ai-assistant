/**
 * Administrator observability and configuration: metrics, the model
 * catalogue, and the audit trail.
 *
 * Every endpoint behind this page is admin-only server-side. The audit trail
 * names who did what from where, which is exactly the sort of data that must
 * not be readable by the people it describes.
 */
import { useEffect, useState } from "react";

import {
  useAddProviderModelMutation,
  useDeleteProviderModelMutation,
  useGetAuditEventsQuery,
  useGetChatProvidersQuery,
  useGetEmbeddingProvidersQuery,
  useGetMetricsQuery,
  useGetProviderModelsQuery,
  useSeedProviderModelsMutation,
  useUpdateProviderModelMutation,
} from "../api/apiSlice";
import type { ProviderModel } from "../api/types";
import { useAppDispatch } from "../store/hooks";
import { toastRaised } from "../store/uiSlice";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorAlert,
  Field,
  Input,
  Metric,
  Select,
  SkeletonRows,
  Tabs,
  Timestamp,
} from "../components/ui";

const TABS = ["Metrics", "Models", "Audit trail"] as const;
type Tab = (typeof TABS)[number];

export default function Administration() {
  const [tab, setTab] = useState<Tab>("Metrics");

  return (
    <div className="content">
      <div className="page-header">
        <h2>Administration</h2>
        <p>Operational health, which models users may pick, and the security audit trail.</p>
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      {tab === "Metrics" && <MetricsTab />}
      {tab === "Models" && <ModelsTab />}
      {tab === "Audit trail" && <AuditTab />}
    </div>
  );
}

function MetricsTab() {
  const { data: metrics, error, isLoading, isFetching, refetch } = useGetMetricsQuery();

  if (error) return <ErrorAlert error={error} />;
  if (isLoading || !metrics) return <SkeletonRows rows={5} />;

  return (
    <div className="stack">
      <div>
        <div className="section-label" style={{ padding: 0, marginBottom: "var(--space-2)" }}>
          Knowledge base
        </div>
        <div className="metric-grid">
          <Metric label="Documents" value={metrics.documents_total} icon="document" />
          <Metric label="Indexed chunks" value={metrics.document_chunks_total} icon="library" />
        </div>
      </div>

      <div>
        <div className="section-label" style={{ padding: 0, marginBottom: "var(--space-2)" }}>
          Usage
        </div>
        <div className="metric-grid">
          <Metric label="Conversations" value={metrics.chat_sessions_total} icon="chat" />
          <Metric label="Messages" value={metrics.chat_messages_total} icon="chat" />
          <Metric label="Projects" value={metrics.projects_total} icon="folder" />
        </div>
      </div>

      <div>
        <div className="section-label" style={{ padding: 0, marginBottom: "var(--space-2)" }}>
          Accounts
        </div>
        <div className="metric-grid">
          <Metric label="Users" value={metrics.users_total} icon="user" />
          <Metric label="Administrators" value={metrics.users_admin} icon="shield" />
          <Metric
            label="Failed sign-ins (24h)"
            value={metrics.logins_failed_last_24h}
            icon="warning"
            attention={metrics.logins_failed_last_24h > 0}
          />
        </div>
        {metrics.logins_failed_last_24h > 0 && (
          <p className="muted" style={{ marginTop: "var(--space-2)" }}>
            Repeated failures from one address can indicate credential stuffing. Filter the audit
            trail by "login.failed" to see the detail.
          </p>
        )}
      </div>

      <div>
        <Button icon="refresh" loading={isFetching} onClick={() => void refetch()}>
          Refresh
        </Button>
      </div>
    </div>
  );
}

/**
 * The model catalogue.
 *
 * Changes apply immediately: the server re-reads the catalogue on the next
 * request, and these mutations invalidate the "Provider" tag, so the sidebar
 * pickers update without a reload.
 */
function ModelsTab() {
  const dispatch = useAppDispatch();
  const { data: rows, error, isLoading } = useGetProviderModelsQuery();
  const [seed, seedState] = useSeedProviderModelsMutation();

  if (error) return <ErrorAlert error={error} />;
  if (isLoading || !rows) return <SkeletonRows rows={5} />;

  if (rows.length === 0) {
    return (
      <div className="stack">
        <ErrorAlert error={seedState.error} />
        <EmptyState
          icon="sparkles"
          title="The catalogue is empty"
          body="The providers' built-in defaults are being used. Load them into the database to start managing which models users can pick."
          action={
            <Button
              variant="primary"
              icon="plus"
              loading={seedState.isLoading}
              onClick={async () => {
                const added = await seed().unwrap();
                dispatch(toastRaised("success", added + " model(s) added."));
              }}
            >
              Load default models
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="stack">
      <Alert kind="info">
        Changes take effect immediately - no restart and no code change. Users see only enabled
        models.
      </Alert>

      <AddModelForm />

      {(["chat", "embedding"] as const).map((kind) => {
        const forKind = rows.filter((row) => row.kind === kind);
        if (forKind.length === 0) return null;
        return (
          <div key={kind} className="stack-sm">
            <div className="section-label" style={{ padding: 0 }}>
              {kind === "chat" ? "Chat models" : "Embedding models"}
            </div>
            {kind === "embedding" && (
              <p className="muted">
                Documents are indexed per embedding model. Disable rather than delete one that
                documents were indexed with, or those documents stop being searchable.
              </p>
            )}
            {[...new Set(forKind.map((row) => row.provider))].sort().map((provider) => (
              <Card key={provider} tight title={provider}>
                {forKind
                  .filter((row) => row.provider === provider)
                  .map((row) => (
                    <ModelRow key={row.id} model={row} />
                  ))}
              </Card>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function AddModelForm() {
  const dispatch = useAppDispatch();
  const [addModel, { error, isLoading }] = useAddProviderModelMutation();
  const chatProviders = useGetChatProvidersQuery();
  const embeddingProviders = useGetEmbeddingProvidersQuery();

  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"chat" | "embedding">("chat");
  const [provider, setProvider] = useState("");
  const [modelName, setModelName] = useState("");
  const [displayName, setDisplayName] = useState("");

  const available = (kind === "chat" ? chatProviders.data : embeddingProviders.data) ?? [];

  useEffect(() => {
    setProvider(available[0]?.provider ?? "");
  }, [kind, available]);

  if (!open) {
    return (
      <div>
        <Button icon="plus" onClick={() => setOpen(true)}>
          Add a model
        </Button>
      </div>
    );
  }

  const submit = async () => {
    if (!modelName.trim() || !provider) return;
    try {
      await addModel({
        kind,
        provider,
        model_name: modelName.trim(),
        display_name: displayName.trim() || null,
      }).unwrap();
      dispatch(toastRaised("success", modelName.trim() + " added."));
      setModelName("");
      setDisplayName("");
      setOpen(false);
    } catch {
      /* shown inline */
    }
  };

  return (
    <Card title="Add a model">
      <div className="stack">
        <ErrorAlert error={error} />
        <Field label="Type">
          {(id) => (
            <Select
              id={id}
              value={kind}
              onChange={(event) => setKind(event.target.value as "chat" | "embedding")}
            >
              <option value="chat">Chat</option>
              <option value="embedding">Embedding</option>
            </Select>
          )}
        </Field>
        <Field label="Provider">
          {(id) => (
            <Select id={id} value={provider} onChange={(event) => setProvider(event.target.value)}>
              {available.map((entry) => (
                <option key={entry.provider} value={entry.provider}>
                  {entry.display_name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Model name" hint="Exactly as the provider's API expects it.">
          {(id) => (
            <Input
              id={id}
              value={modelName}
              onChange={(event) => setModelName(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
            />
          )}
        </Field>
        <Field label="Display name (optional)" hint="A friendlier label for the picker.">
          {(id) => (
            <Input
              id={id}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          )}
        </Field>
        <div className="row">
          <Button variant="primary" loading={isLoading} disabled={!modelName.trim()} onClick={submit}>
            Add model
          </Button>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </div>
    </Card>
  );
}

function ModelRow({ model }: { model: ProviderModel }) {
  const dispatch = useAppDispatch();
  const [updateModel, updateState] = useUpdateProviderModelMutation();
  const [deleteModel, deleteState] = useDeleteProviderModelMutation();
  const [confirming, setConfirming] = useState(false);

  const remove = async () => {
    try {
      await deleteModel(model.id).unwrap();
      dispatch(toastRaised("success", model.model_name + " removed."));
      setConfirming(false);
    } catch {
      /* shown inline */
    }
  };

  return (
    <div className="card-row">
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="row" style={{ gap: "var(--space-2)" }}>
          <span className="truncate" style={{ fontWeight: 600 }}>
            {model.display_name || model.model_name}
          </span>
          {!model.is_enabled && <Badge tone="warning">Disabled</Badge>}
        </div>
        {model.display_name && <div className="muted truncate">{model.model_name}</div>}
        <ErrorAlert error={updateState.error ?? deleteState.error} />
      </div>

      <Button
        size="sm"
        loading={updateState.isLoading}
        onClick={() => void updateModel({ id: model.id, is_enabled: !model.is_enabled })}
      >
        {model.is_enabled ? "Disable" : "Enable"}
      </Button>
      <Button
        variant="danger"
        size="sm"
        icon="trash"
        aria-label={"Remove " + model.model_name}
        onClick={() => setConfirming(true)}
      />

      <ConfirmDialog
        open={confirming}
        title={"Remove " + model.model_name + "?"}
        body={
          model.kind === "embedding"
            ? "Documents indexed with this embedding model will stop being searchable. Disabling hides it from the picker while keeping them queryable."
            : "It will disappear from every user's model picker. Disabling is reversible; removing is not."
        }
        confirmLabel="Remove model"
        destructive
        busy={deleteState.isLoading}
        onConfirm={remove}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}

const ACTIONS = [
  "All",
  "login.succeeded",
  "login.failed",
  "logout",
  "user.registered",
  "user.role_changed",
  "user.password_reset",
  "document.uploaded",
  "document.deleted",
  "knowledge_base.cleared",
  "model_catalogue.changed",
] as const;

/** Actions worth colouring, so a failure or a destructive act stands out. */
const ACTION_TONE: Record<string, "danger" | "warning" | "accent"> = {
  "login.failed": "warning",
  "knowledge_base.cleared": "danger",
  "document.deleted": "danger",
  "user.role_changed": "accent",
  "user.password_reset": "accent",
};

function AuditTab() {
  const [action, setAction] = useState<string>("All");
  const [email, setEmail] = useState("");
  const [debouncedEmail, setDebouncedEmail] = useState("");

  // Debounced so typing an address does not fire a request per keystroke.
  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedEmail(email.trim()), 250);
    return () => window.clearTimeout(handle);
  }, [email]);

  const { data: events, error, isLoading } = useGetAuditEventsQuery({
    action: action === "All" ? undefined : action,
    user_email: debouncedEmail || undefined,
  });

  return (
    <div className="stack">
      <p className="muted">
        Security-relevant actions, most recent first. Never contains document text.
      </p>

      <div className="row-wrap">
        <div style={{ flex: "1 1 12rem" }}>
          <Field label="Action">
            {(id) => (
              <Select id={id} value={action} onChange={(event) => setAction(event.target.value)}>
                {ACTIONS.map((entry) => (
                  <option key={entry} value={entry}>
                    {entry}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        <div style={{ flex: "1 1 12rem" }}>
          <Field label="Account">
            {(id) => (
              <Input
                id={id}
                placeholder="email@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            )}
          </Field>
        </div>
      </div>

      <ErrorAlert error={error} />

      {isLoading ? (
        <SkeletonRows rows={6} />
      ) : (events ?? []).length === 0 ? (
        <EmptyState
          icon="shield"
          title="No matching events"
          body="Nothing has been recorded for this filter yet."
        />
      ) : (
        <>
          <p className="muted">{(events ?? []).length} event(s)</p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Action</th>
                  <th>Account</th>
                  <th>IP</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {(events ?? []).map((event) => (
                  <tr key={event.id}>
                    <td className="cell-nowrap">
                      <Timestamp value={event.created_at} relative />
                    </td>
                    <td className="cell-nowrap">
                      {ACTION_TONE[event.action] ? (
                        <Badge tone={ACTION_TONE[event.action]}>{event.action}</Badge>
                      ) : (
                        event.action
                      )}
                    </td>
                    <td className="cell-nowrap">{event.user_email ?? "-"}</td>
                    <td className="cell-nowrap">{event.ip_address ?? "-"}</td>
                    <td className="cell-wrap">{summariseDetail(event.detail)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function summariseDetail(detail: Record<string, unknown> | null): string {
  if (!detail) return "-";
  return Object.entries(detail)
    .map(([key, value]) => key + "=" + String(value))
    .join(", ");
}
