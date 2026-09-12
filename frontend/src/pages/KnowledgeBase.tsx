/**
 * Admin knowledge-base management.
 *
 * Admin-only navigation, but that is presentation: every endpoint here is
 * enforced server-side, so hiding this page from an end user is convenience,
 * not security.
 */
import { useEffect, useState } from "react";

import {
  useAskMutation,
  useClearDocumentsMutation,
  useDeleteDocumentMutation,
  useGetDocumentsQuery,
  useUploadDocumentsMutation,
} from "../api/apiSlice";
import type { DocumentRead } from "../api/types";
import { useAppDispatch, useAppSelector } from "../store/hooks";
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
  Icon,
  Input,
  Metric,
  Select,
  SkeletonRows,
  Tabs,
  Timestamp,
} from "../components/ui";

const TABS = ["Add documents", "Manage", "Test retrieval"] as const;
type Tab = (typeof TABS)[number];

export default function KnowledgeBase() {
  const [tab, setTab] = useState<Tab>("Add documents");
  const { data: documents, error, isLoading } = useGetDocumentsQuery();

  return (
    <div className="content">
      <div className="page-header">
        <h2>Shared knowledge base</h2>
        <p>
          Documents indexed here answer questions for every user. End users never see the documents
          themselves, or that retrieval is happening at all.
        </p>
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      <ErrorAlert error={error} />

      {isLoading ? (
        <SkeletonRows rows={4} />
      ) : (
        <>
          {tab === "Add documents" && <UploadTab />}
          {tab === "Manage" && <ManageTab documents={documents ?? []} />}
          {tab === "Test retrieval" && <TestTab documents={documents ?? []} />}
        </>
      )}
    </div>
  );
}

function UploadTab() {
  const dispatch = useAppDispatch();
  const { embeddingProvider, embeddingModel } = useAppSelector((state) => state.models);
  const [upload, { error, isLoading, data: result }] = useUploadDocumentsMutation();
  const [files, setFiles] = useState<File[]>([]);
  const [inputKey, setInputKey] = useState(0);

  const ready = Boolean(embeddingProvider && embeddingModel);

  const submit = async () => {
    if (files.length === 0 || !ready) return;
    try {
      const uploaded = await upload({
        files,
        embedding_provider: embeddingProvider,
        embedding_model: embeddingModel,
      }).unwrap();
      setFiles([]);
      // Remount the file input so the browser clears its selection.
      setInputKey((value) => value + 1);
      // A batch can partly succeed, so the toast reflects both outcomes and
      // the detail stays on screen below rather than vanishing with it.
      dispatch(
        uploaded.warnings.length > 0
          ? toastRaised(
              "error",
              uploaded.documents.length +
                " indexed, " +
                uploaded.warnings.length +
                " failed.",
            )
          : toastRaised("success", uploaded.documents.length + " document(s) indexed."),
      );
    } catch {
      /* shown inline */
    }
  };

  return (
    <Card
      title="Add PDFs"
      subtitle={"Indexed with " + (embeddingProvider || "-") + " / " + (embeddingModel || "-")}
    >
      <div className="stack">
        {!ready && (
          <Alert kind="info">Choose an embedding model in the sidebar before uploading.</Alert>
        )}

        <Field
          label="PDF files"
          hint="Scanned PDFs are OCR-read automatically, which takes longer."
        >
          {(id) => (
            <Input
              key={inputKey}
              id={id}
              type="file"
              accept="application/pdf"
              multiple
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
          )}
        </Field>

        {files.length > 0 && (
          <div className="stack-sm">
            {files.map((file) => (
              <div key={file.name} className="row">
                <Icon name="document" size={14} style={{ color: "var(--text-muted)" }} />
                <span className="truncate" style={{ flex: 1 }}>
                  {file.name}
                </span>
                <span className="muted">{Math.round(file.size / 1024)} KB</span>
              </div>
            ))}
          </div>
        )}

        <ErrorAlert error={error} />
        {result && result.warnings.length > 0 && (
          <Alert kind="warning">
            <div>These files were not indexed:</div>
            <ul>
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </Alert>
        )}
        {isLoading && (
          <Alert kind="info">
            Indexing. Scanned PDFs and local embedding models can take several minutes - this page
            can be left open.
          </Alert>
        )}

        <div>
          <Button
            variant="primary"
            icon="upload"
            loading={isLoading}
            disabled={files.length === 0 || !ready}
            onClick={submit}
          >
            Index {files.length > 0 ? files.length + " document(s)" : "documents"}
          </Button>
        </div>
      </div>
    </Card>
  );
}

function ManageTab({ documents }: { documents: DocumentRead[] }) {
  const dispatch = useAppDispatch();
  const [deleteDocument, deleteState] = useDeleteDocumentMutation();
  const [clearDocuments, clearState] = useClearDocumentsMutation();
  const [confirmClear, setConfirmClear] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<DocumentRead | null>(null);

  if (documents.length === 0) {
    return (
      <EmptyState
        icon="library"
        title="The knowledge base is empty"
        body="Nothing is indexed yet, so questions cannot be answered. Add a PDF to get started."
      />
    );
  }

  const chunks = documents.reduce((total, document) => total + (document.chunk_count ?? 0), 0);

  const remove = async () => {
    if (!pendingDelete) return;
    try {
      await deleteDocument(pendingDelete.id).unwrap();
      dispatch(toastRaised("success", pendingDelete.filename + " deleted."));
      setPendingDelete(null);
    } catch {
      /* shown inline */
    }
  };

  const clearAll = async () => {
    try {
      await clearDocuments().unwrap();
      dispatch(toastRaised("success", "Knowledge base cleared."));
      setConfirmClear(false);
    } catch {
      /* shown inline */
    }
  };

  return (
    <div className="stack">
      <div className="metric-grid">
        <Metric label="Documents" value={documents.length} icon="document" />
        <Metric label="Indexed chunks" value={chunks} icon="library" />
      </div>

      <ErrorAlert error={deleteState.error ?? clearState.error} />

      <div className="stack-sm">
        {documents.map((document) => (
          <Card key={document.id} tight>
            <div className="row">
              <Icon name="document" size={18} style={{ color: "var(--text-muted)" }} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="truncate" style={{ fontWeight: 600 }}>
                  {document.filename}
                </div>
                <div className="row-wrap" style={{ marginTop: "var(--space-1)" }}>
                  <Badge tone={document.status === "indexed" ? "success" : "danger"}>
                    {document.status}
                  </Badge>
                  <span className="muted">
                    {document.page_count ?? 0} pages, {document.chunk_count ?? 0} chunks
                  </span>
                  <span className="muted">
                    {document.embedding_provider}/{document.embedding_model}
                  </span>
                  <span className="muted">
                    {Math.round(document.file_size_bytes / 1024)} KB
                  </span>
                  <span className="muted">
                    <Timestamp value={document.created_at} relative />
                  </span>
                </div>
                {document.failure_reason && (
                  <div style={{ marginTop: "var(--space-2)" }}>
                    <Alert kind="error">{document.failure_reason}</Alert>
                  </div>
                )}
              </div>
              <Button
                variant="danger"
                size="sm"
                icon="trash"
                aria-label={"Delete " + document.filename}
                onClick={() => setPendingDelete(document)}
              />
            </div>
          </Card>
        ))}
      </div>

      <Card title="Danger zone">
        <Alert kind="warning">
          Clearing removes every document and every embedding. All users lose access to these
          answers immediately.
        </Alert>
        <div style={{ marginTop: "var(--space-4)" }}>
          <Button variant="danger" icon="trash" onClick={() => setConfirmClear(true)}>
            Clear knowledge base
          </Button>
        </div>
      </Card>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={"Delete " + (pendingDelete?.filename ?? "") + "?"}
        body="Its embeddings are removed, so answers that relied on it will stop citing it."
        confirmLabel="Delete document"
        destructive
        busy={deleteState.isLoading}
        onConfirm={remove}
        onCancel={() => setPendingDelete(null)}
      />

      <ConfirmDialog
        open={confirmClear}
        title="Clear the entire knowledge base?"
        body={
          "All " +
          documents.length +
          " document(s) and their embeddings will be deleted. This affects every user, not just you, and cannot be undone."
        }
        confirmLabel="Clear everything"
        destructive
        busy={clearState.isLoading}
        onConfirm={clearAll}
        onCancel={() => setConfirmClear(false)}
      />
    </div>
  );
}

/**
 * Ask a question against one document, to see what it alone supports.
 *
 * Scoping to a single document is what makes this diagnostic: if an answer is
 * missing from the shared knowledge base, this shows whether the source
 * document actually contains it, separating a corpus gap from a retrieval
 * problem. The backend uses the document's own indexing config, so no
 * embedding selection is needed here.
 */
function TestTab({ documents }: { documents: DocumentRead[] }) {
  const { chatProvider, chatModel } = useAppSelector((state) => state.models);
  const [ask, { data: answer, error, isLoading }] = useAskMutation();
  const [documentId, setDocumentId] = useState("");
  const [question, setQuestion] = useState("");

  useEffect(() => {
    if (!documentId && documents.length > 0) setDocumentId(documents[0]!.id);
  }, [documents, documentId]);

  if (documents.length === 0) {
    return (
      <EmptyState
        icon="document"
        title="Nothing to test against"
        body="Add a document first, then ask a question scoped to it alone."
      />
    );
  }
  if (!chatProvider || !chatModel) {
    return <Alert kind="info">Choose a chat model in the sidebar first.</Alert>;
  }

  const run = () => {
    if (!question.trim()) return;
    void ask({
      question: question.trim(),
      provider: chatProvider,
      model: chatModel,
      document_id: documentId,
    });
  };

  return (
    <div className="stack">
      <Card
        title="Test one document"
        subtitle="Separates a gap in the corpus from a retrieval problem."
      >
        <div className="stack">
          <Field label="Document">
            {(id) => (
              <Select
                id={id}
                value={documentId}
                onChange={(event) => setDocumentId(event.target.value)}
              >
                {documents.map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.filename}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Question">
            {(id) => (
              <Input
                id={id}
                placeholder="Ask something this document should answer"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && run()}
              />
            )}
          </Field>
          <div>
            <Button
              variant="primary"
              icon="search"
              loading={isLoading}
              disabled={!question.trim()}
              onClick={run}
            >
              Run
            </Button>
          </div>
        </div>
      </Card>

      <ErrorAlert error={error} />

      {answer && (
        <Card title="Answer">
          <div className="message-text measure">{answer.answer}</div>

          {answer.sources.length > 0 ? (
            <div className="source-list" style={{ marginTop: "var(--space-3)" }}>
              {answer.sources.map((source, index) => (
                <span className="source-chip" key={index}>
                  <Icon name="document" size={11} />
                  {source.document}
                  <span className="muted">p.{source.page}</span>
                </span>
              ))}
            </div>
          ) : (
            <p className="muted" style={{ marginTop: "var(--space-3)" }}>
              No sources were cited.
            </p>
          )}

          <div className="metric-grid" style={{ marginTop: "var(--space-5)" }}>
            <Metric label="Retrieval" value={Math.round(answer.retrieval_time_ms) + " ms"} />
            <Metric label="Generation" value={Math.round(answer.llm_time_ms) + " ms"} />
            <Metric label="Total" value={Math.round(answer.total_time_ms) + " ms"} />
          </div>

          {answer.crag && (
            <details style={{ marginTop: "var(--space-4)" }}>
              <summary className="muted" style={{ cursor: "pointer" }}>
                Pipeline diagnostics
              </summary>
              <div className="table-wrap" style={{ marginTop: "var(--space-2)" }}>
                <table className="table">
                  <tbody>
                    <tr>
                      <th style={{ width: "40%" }}>Context verdict</th>
                      <td>{answer.crag.context_verdict ?? "n/a"}</td>
                    </tr>
                    <tr>
                      <th>Context quality</th>
                      <td>
                        {answer.crag.context_quality === null
                          ? "n/a"
                          : answer.crag.context_quality.toFixed(3)}
                      </td>
                    </tr>
                    <tr>
                      <th>Correction attempts</th>
                      <td>{answer.crag.correction_attempts}</td>
                    </tr>
                    {answer.crag.rewritten_query && (
                      <tr>
                        <th>Rewritten query</th>
                        <td className="cell-wrap">{answer.crag.rewritten_query}</td>
                      </tr>
                    )}
                    <tr>
                      <th>Groundedness</th>
                      <td>{answer.crag.groundedness_verdict ?? "n/a"}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </Card>
      )}
    </div>
  );
}
