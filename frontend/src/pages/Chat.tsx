/**
 * The conversation - the whole product, as far as an end user is concerned.
 *
 * All behaviour lives in `chatSlice`; this file renders state and dispatches.
 * That split is why the transcript survives navigating to another page and
 * back: it is store state, not component state.
 */
import { useEffect, useRef, useState } from "react";

import { useAppDispatch, useAppSelector } from "../store/hooks";
import {
  errorDismissed,
  retryLastAnswer,
  sendQuestion,
  type Message,
} from "../store/chatSlice";
import {
  Alert,
  AutoTextarea,
  Button,
  CopyButton,
  EmptyState,
  Icon,
  IconButton,
} from "../components/ui";

/** How far from the bottom still counts as "following the conversation". */
const NEAR_BOTTOM_PX = 120;

export default function Chat() {
  const dispatch = useAppDispatch();
  const { messages, streaming, partial, status, error } = useAppSelector((state) => state.chat);
  const modelsReady = useAppSelector((state) => state.models.ready);
  const chatModel = useAppSelector((state) => state.models.chatModel);

  const [question, setQuestion] = useState("");
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  // Follow new content only while the user has not scrolled up to read
  // something earlier - yanking them back mid-read would be worse than a
  // stale viewport.
  useEffect(() => {
    if (!pinnedToBottom) return;
    const node = transcriptRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, partial, status, pinnedToBottom]);

  const onScroll = () => {
    const node = transcriptRef.current;
    if (!node) return;
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    setPinnedToBottom(distance < NEAR_BOTTOM_PX);
  };

  const scrollToLatest = () => {
    const node = transcriptRef.current;
    if (node) node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
    setPinnedToBottom(true);
  };

  const send = () => {
    const asked = question.trim();
    if (!asked || streaming) return;
    setQuestion("");
    setPinnedToBottom(true);
    void dispatch(sendQuestion(asked));
  };

  const lastIndex = messages.length - 1;
  const empty = messages.length === 0 && !streaming;

  return (
    <>
      <div className="transcript-holder">
        <div className="transcript" ref={transcriptRef} onScroll={onScroll}>
          <div className="transcript-inner">
            {empty && (
              <EmptyState
                icon="sparkles"
                title="Ask about your organisation's knowledge base"
                body="Answers are drawn only from the documents your administrators have indexed, and every answer cites its sources."
              />
            )}

            {messages.map((message, index) => (
              <MessageView
                key={index}
                message={message}
                canRetry={index === lastIndex && message.role === "assistant" && !streaming}
                onRetry={() => void dispatch(retryLastAnswer())}
              />
            ))}

            {status && (
              <div className="message message-assistant">
                <span className="avatar avatar-assistant" aria-hidden="true">
                  <Icon name="sparkles" size={14} />
                </span>
                <div className="message-body">
                  <div className="message-who">Assistant</div>
                  <div className="thinking" role="status">
                    <span className="spinner" />
                    {status}
                  </div>
                </div>
              </div>
            )}

            {partial && (
              <div className="message message-assistant">
                <span className="avatar avatar-assistant" aria-hidden="true">
                  <Icon name="sparkles" size={14} />
                </span>
                <div className="message-body">
                  <div className="message-who">Assistant</div>
                  <div className="message-text">
                    {partial}
                    <span className="caret" />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {!pinnedToBottom && (
          <Button
            className="scroll-latest"
            size="sm"
            icon="arrowDown"
            onClick={scrollToLatest}
          >
            Jump to latest
          </Button>
        )}
      </div>

      <div className="composer-wrap">
        {error && (
          <div style={{ maxWidth: "var(--content-max)", margin: "0 auto var(--space-3)" }}>
            <Alert kind="error">
              <div className="row">
                <span style={{ flex: 1 }}>{error}</span>
                <IconButton
                  icon="close"
                  label="Dismiss error"
                  onClick={() => dispatch(errorDismissed())}
                />
              </div>
            </Alert>
          </div>
        )}
        {!modelsReady && (
          <div style={{ maxWidth: "var(--content-max)", margin: "0 auto var(--space-3)" }}>
            <Alert kind="warning">
              No chat model is available. Ask an administrator to configure one.
            </Alert>
          </div>
        )}

        <div className="composer">
          <AutoTextarea
            aria-label="Your question"
            placeholder="Ask a question..."
            value={question}
            rows={1}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends; Shift+Enter starts a new line.
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            disabled={streaming}
          />
          <Button
            variant="primary"
            icon="send"
            aria-label="Send question"
            loading={streaming}
            disabled={!question.trim()}
            onClick={send}
          />
        </div>
        <div className="composer-hint">
          <span>Enter to send, Shift+Enter for a new line.</span>
          <span className="spacer" />
          {/* Which model is answering is worth seeing without opening the
              sidebar - it is the one setting that changes the output. */}
          {chatModel && (
            <span className="composer-model">
              <Icon name="sparkles" size={11} />
              {chatModel}
            </span>
          )}
        </div>
      </div>
    </>
  );
}

function MessageView({
  message,
  canRetry,
  onRetry,
}: {
  message: Message;
  canRetry: boolean;
  onRetry: () => void;
}) {
  const isUser = message.role === "user";
  return (
    <div
      className={
        "message message-" + message.role + (message.failed ? " message-failed" : "")
      }
    >
      <span
        className={"avatar" + (isUser ? "" : " avatar-assistant")}
        aria-hidden="true"
      >
        {isUser ? "You".slice(0, 1) : <Icon name="sparkles" size={14} />}
      </span>

      <div className="message-body">
        <div className="message-who">{isUser ? "You" : "Assistant"}</div>
        <div className="message-text">{message.content}</div>

        {message.sources && message.sources.length > 0 && (
          <details className="sources">
            <summary>
              <Icon name="document" size={12} />
              {message.sources.length} source{message.sources.length === 1 ? "" : "s"}
            </summary>
            <div className="source-list">
              {message.sources.map((source, index) => (
                <span className="source-chip" key={index}>
                  <Icon name="document" size={11} />
                  {source.document}
                  <span className="muted">p.{source.page}</span>
                </span>
              ))}
            </div>
          </details>
        )}

        {!isUser && (
          <div className="message-actions">
            {!message.failed && <CopyButton text={message.content} />}
            {/* Only the newest answer can be retried: redoing an earlier one
                would orphan every exchange that followed it. */}
            {canRetry && (
              <Button variant="ghost" size="sm" icon="refresh" onClick={onRetry}>
                Retry
              </Button>
            )}
            {message.meta && <span className="muted">{message.meta}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
