/**
 * Chat navigation: new chat, search, projects, recent conversations.
 *
 * No manual refetching: every mutation declares the tags it invalidates, so
 * renaming a chat or creating a project updates the list on its own.
 *
 * Search replaces the tree rather than filtering inside it - mixing matches
 * into folders makes it unclear what matched and what is merely nearby.
 */
import { useEffect, useState } from "react";

import {
  useCreateProjectMutation,
  useDeleteChatSessionMutation,
  useDeleteProjectMutation,
  useGetChatsQuery,
  useGetProjectChatsQuery,
  useGetProjectsQuery,
  useMoveChatMutation,
  useRenameChatMutation,
  useRenameProjectMutation,
} from "../api/apiSlice";
import type { ChatSummary, ProjectRead } from "../api/types";
import { conversationCleared, openConversation } from "../store/chatSlice";
import { useAppDispatch, useAppSelector } from "../store/hooks";
import { toastRaised } from "../store/uiSlice";
import {
  Button,
  ConfirmDialog,
  ErrorAlert,
  Field,
  Icon,
  IconButton,
  Input,
  Select,
  Skeleton,
} from "./ui";

export default function ChatHistory({ onNavigate }: { onNavigate: () => void }) {
  const dispatch = useAppDispatch();
  const activeChatId = useAppSelector((state) => state.chat.sessionId);

  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [addingProject, setAddingProject] = useState(false);
  const [projectName, setProjectName] = useState("");

  // Debounced so typing does not fire a request per keystroke.
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(handle);
  }, [search]);

  const projectsQuery = useGetProjectsQuery();
  const ungroupedQuery = useGetChatsQuery({ ungrouped_only: true }, { skip: debounced !== "" });
  const searchQuery = useGetChatsQuery({ search: debounced }, { skip: debounced === "" });
  const [createProject, createState] = useCreateProjectMutation();

  const projects = projectsQuery.data ?? [];
  const searching = debounced !== "";
  const results = searchQuery.data ?? [];
  const recent = ungroupedQuery.data ?? [];

  const submitProject = async () => {
    const name = projectName.trim();
    if (!name) return;
    try {
      await createProject({ name }).unwrap();
      setProjectName("");
      setAddingProject(false);
      dispatch(toastRaised("success", "Project created."));
    } catch {
      /* shown inline below */
    }
  };

  return (
    <div className="stack-sm">
      <Button
        variant="primary"
        icon="plus"
        block
        onClick={() => {
          dispatch(conversationCleared());
          onNavigate();
        }}
      >
        New chat
      </Button>

      <div style={{ position: "relative" }}>
        <Input
          aria-label="Search chats"
          placeholder="Search chats..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          style={{ paddingLeft: "2rem" }}
        />
        <Icon
          name="search"
          size={14}
          style={{
            position: "absolute",
            left: "0.65rem",
            top: "50%",
            transform: "translateY(-50%)",
            color: "var(--text-muted)",
          }}
        />
      </div>

      <ErrorAlert error={projectsQuery.error ?? ungroupedQuery.error ?? searchQuery.error} />
      <ErrorAlert error={createState.error} />

      {searching ? (
        <>
          <div className="section-label">
            {results.length} result{results.length === 1 ? "" : "s"}
          </div>
          {searchQuery.isFetching && results.length === 0 && <Skeleton height={28} />}
          <div className="chat-list">
            {results.map((chat) => (
              <ChatRow
                key={chat.id}
                chat={chat}
                projects={projects}
                activeChatId={activeChatId}
                onOpen={onNavigate}
              />
            ))}
          </div>
          {!searchQuery.isFetching && results.length === 0 && (
            <div className="muted" style={{ padding: "0 var(--space-2)" }}>
              Nothing matched. Search covers titles and message text.
            </div>
          )}
        </>
      ) : (
        <>
          <div className="section-label">
            <Icon name="folder" size={12} />
            Projects
            <div className="spacer" />
            <IconButton
              icon="plus"
              label="New project"
              onClick={() => setAddingProject((value) => !value)}
            />
          </div>

          {addingProject && (
            <div className="row">
              <Input
                autoFocus
                aria-label="Project name"
                placeholder="Project name"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void submitProject();
                  if (event.key === "Escape") setAddingProject(false);
                }}
              />
              <Button size="sm" loading={createState.isLoading} onClick={submitProject}>
                Add
              </Button>
            </div>
          )}

          {projects.map((project) => (
            <ProjectNode
              key={project.id}
              project={project}
              projects={projects}
              activeChatId={activeChatId}
              onOpen={onNavigate}
            />
          ))}
          {projects.length === 0 && !addingProject && (
            <div className="muted" style={{ padding: "0 var(--space-2)" }}>
              No projects yet.
            </div>
          )}

          <div className="section-label" style={{ marginTop: "var(--space-2)" }}>
            <Icon name="chat" size={12} />
            Recent
          </div>
          {ungroupedQuery.isLoading && <Skeleton height={28} />}
          <div className="chat-list">
            {recent.map((chat) => (
              <ChatRow
                key={chat.id}
                chat={chat}
                projects={projects}
                activeChatId={activeChatId}
                onOpen={onNavigate}
              />
            ))}
          </div>
          {!ungroupedQuery.isLoading && recent.length === 0 && (
            <div className="muted" style={{ padding: "0 var(--space-2)" }}>
              No chats yet. Ask a question to start one.
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface RowContext {
  projects: ProjectRead[];
  activeChatId: string | null;
  onOpen: () => void;
}

function ProjectNode({ project, ...context }: { project: ProjectRead } & RowContext) {
  const dispatch = useAppDispatch();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const [confirming, setConfirming] = useState(false);

  // Chats are fetched only when a folder is opened, so a sidebar with many
  // projects costs one request rather than one per project.
  const chatsQuery = useGetProjectChatsQuery(project.id, { skip: !open });
  const [renameProject, renameState] = useRenameProjectMutation();
  const [deleteProject, deleteState] = useDeleteProjectMutation();

  const remove = async () => {
    try {
      await deleteProject(project.id).unwrap();
      setConfirming(false);
      dispatch(toastRaised("success", "Project deleted. Its chats moved to Recent."));
    } catch {
      /* shown inline */
    }
  };

  return (
    <details
      className="project-group"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="project-summary">
        <Icon name="chevronRight" size={12} className="project-chevron" />
        <span className="truncate" style={{ flex: 1 }}>
          {project.name}
        </span>
        <span className="muted">{project.chat_count}</span>
      </summary>

      <div className="project-children">
        <ErrorAlert error={renameState.error ?? deleteState.error ?? chatsQuery.error} />

        {editing ? (
          <div className="row" style={{ margin: "var(--space-2) 0" }}>
            <Input
              autoFocus
              aria-label="Project name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Button
              size="sm"
              loading={renameState.isLoading}
              onClick={async () => {
                await renameProject({ id: project.id, name: name.trim() });
                setEditing(false);
              }}
            >
              Save
            </Button>
          </div>
        ) : (
          <div className="row" style={{ margin: "var(--space-1) 0" }}>
            <IconButton icon="edit" label="Rename project" onClick={() => setEditing(true)} />
            <IconButton icon="trash" label="Delete project" onClick={() => setConfirming(true)} />
          </div>
        )}

        {chatsQuery.isLoading && <Skeleton height={24} />}
        <div className="chat-list">
          {(chatsQuery.data ?? []).map((chat) => (
            <ChatRow key={chat.id} chat={chat} {...context} />
          ))}
        </div>
        {chatsQuery.data?.length === 0 && <div className="muted">No chats yet.</div>}
      </div>

      <ConfirmDialog
        open={confirming}
        title={"Delete " + project.name + "?"}
        body="The conversations inside it are kept - they move back to Recent. Only the folder is removed."
        confirmLabel="Delete project"
        destructive
        busy={deleteState.isLoading}
        onConfirm={remove}
        onCancel={() => setConfirming(false)}
      />
    </details>
  );
}

function ChatRow({ chat, projects, activeChatId, onOpen }: { chat: ChatSummary } & RowContext) {
  const dispatch = useAppDispatch();
  const [menuOpen, setMenuOpen] = useState(false);
  const [title, setTitle] = useState(chat.title);
  const [confirming, setConfirming] = useState(false);
  const isActive = activeChatId === chat.id;

  const [renameChat, renameState] = useRenameChatMutation();
  const [moveChat, moveState] = useMoveChatMutation();
  const [deleteChat, deleteState] = useDeleteChatSessionMutation();

  const remove = async () => {
    try {
      await deleteChat(chat.id).unwrap();
      // The open conversation was just removed; clear the panel rather than
      // leaving orphaned messages on screen.
      if (isActive) dispatch(conversationCleared());
      setConfirming(false);
      setMenuOpen(false);
      dispatch(toastRaised("success", "Chat deleted."));
    } catch {
      /* shown inline */
    }
  };

  return (
    <>
      <div className={"chat-item" + (isActive ? " active" : "")}>
        <button
          className="chat-item-open"
          title={chat.title}
          onClick={() => {
            void dispatch(openConversation(chat.id));
            onOpen();
          }}
        >
          {chat.title || "New chat"}
        </button>
        {/* Collapsed by default; rename/move/delete inline for every chat
            would crowd the sidebar unusably. */}
        <span className="chat-item-menu">
          <IconButton
            icon="more"
            label={"Options for " + (chat.title || "chat")}
            onClick={() => setMenuOpen((open) => !open)}
          />
        </span>
      </div>

      {menuOpen && (
        <div className="popover">
          <ErrorAlert error={renameState.error ?? moveState.error ?? deleteState.error} />

          <Field label="Title">
            {(id) => (
              <Input
                id={id}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") return;
                  void renameChat({ id: chat.id, title: title.trim() });
                  setMenuOpen(false);
                }}
              />
            )}
          </Field>

          <Field label="Project">
            {(id) => (
              <Select
                id={id}
                value={chat.project_id ?? ""}
                onChange={(event) =>
                  void moveChat({
                    id: chat.id,
                    project_id: event.target.value === "" ? null : event.target.value,
                  })
                }
              >
                {/* "No project" is offered explicitly so a chat can be taken
                    out of a folder, not only moved between folders. */}
                <option value="">No project</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <div className="row">
            <Button
              size="sm"
              loading={renameState.isLoading}
              onClick={async () => {
                await renameChat({ id: chat.id, title: title.trim() });
                setMenuOpen(false);
              }}
            >
              Save
            </Button>
            <div className="spacer" />
            <Button variant="danger" size="sm" icon="trash" onClick={() => setConfirming(true)}>
              Delete
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        title="Delete this chat?"
        body="The conversation and its messages are removed permanently."
        confirmLabel="Delete chat"
        destructive
        busy={deleteState.isLoading}
        onConfirm={remove}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}
