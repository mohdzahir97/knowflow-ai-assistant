/**
 * Navigation, chat history, model selection and the account menu.
 *
 * Laid out in three bands: a fixed brand row, a scrolling middle that holds
 * navigation and conversation history, and a pinned footer. Only the middle
 * scrolls, so the model trigger and account row never drift out of reach in
 * a long history.
 *
 * The role decides which links appear. That is presentation only - the
 * backend authorises every request independently, so a client that renders
 * an admin link it should not have gains nothing by it.
 */
import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";

import { useGetChatProvidersQuery, useGetEmbeddingProvidersQuery } from "../api/apiSlice";
import { useAppDispatch, useAppSelector } from "../store/hooks";
import { reconcile } from "../store/modelsSlice";
import { useSession } from "../store/session";
import { sidebarClosed, themeSet, type ThemePreference } from "../store/uiSlice";
import ChatHistory from "./ChatHistory";
import ModelPicker from "./ModelPicker";
import { Icon, IconButton, type IconName } from "./ui";

export default function Sidebar({ showChatHistory }: { showChatHistory: boolean }) {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.ui.sidebarOpen);
  const { isAdmin } = useSession();

  const chatQuery = useGetChatProvidersQuery();
  const embeddingQuery = useGetEmbeddingProvidersQuery();

  // Re-validate the stored selection whenever the catalogue changes, so a
  // model an administrator has since disabled is replaced rather than sent.
  useEffect(() => {
    if (chatQuery.data && embeddingQuery.data) {
      dispatch(reconcile({ chat: chatQuery.data, embedding: embeddingQuery.data }));
    }
  }, [chatQuery.data, embeddingQuery.data, dispatch]);

  const close = () => dispatch(sidebarClosed());

  return (
    <aside className="sidebar" data-open={open}>
      <div className="sidebar-brand">
        <span className="brand-mark">
          <Icon name="sparkles" size={15} />
        </span>
        <span className="brand-name">Knowledge Assistant</span>
        <div className="spacer" />
        <span className="sidebar-toggle">
          <IconButton icon="close" label="Close menu" onClick={close} />
        </span>
      </div>

      <div className="sidebar-scroll">
        <nav className="nav" aria-label="Main">
          <NavItem to="/chat" icon="chat" label="Chat" onNavigate={close} />
          {isAdmin && (
            <NavItem to="/knowledge-base" icon="library" label="Knowledge base" onNavigate={close} />
          )}
          {isAdmin && (
            <NavItem to="/administration" icon="settings" label="Administration" onNavigate={close} />
          )}
        </nav>

        {showChatHistory && (
          <>
            <div className="sidebar-rule" />
            <ChatHistory onNavigate={close} />
          </>
        )}
      </div>

      <div className="sidebar-footer">
        <ModelPicker isAdmin={isAdmin} />
        <AccountMenu />
      </div>
    </aside>
  );
}

function NavItem({
  to,
  icon,
  label,
  onNavigate,
}: {
  to: string;
  icon: IconName;
  label: string;
  onNavigate: () => void;
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
    >
      <Icon name={icon} />
      {label}
    </NavLink>
  );
}

/**
 * The account row, with theme and sign-out behind a menu.
 *
 * Both were previously always-visible controls competing with navigation for
 * attention, despite being used rarely.
 */
function AccountMenu() {
  const dispatch = useAppDispatch();
  const { profile, isAdmin, signOut } = useSession();
  const theme = useAppSelector((state) => state.ui.theme);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const themes: { value: ThemePreference; icon: IconName; label: string }[] = [
    { value: "light", icon: "sun", label: "Light" },
    { value: "dark", icon: "moon", label: "Dark" },
    { value: "system", icon: "settings", label: "System" },
  ];

  return (
    <div className="account" ref={rootRef}>
      <button
        className={"account-trigger" + (open ? " open" : "")}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="avatar" aria-hidden="true">
          {(profile?.email ?? "?").slice(0, 1)}
        </span>
        <span className="account-text">
          <span className="account-name truncate">{profile?.full_name || profile?.email}</span>
          <span className="account-role">{isAdmin ? "Administrator" : "Member"}</span>
        </span>
        <Icon name="chevronDown" size={14} className="model-trigger-chevron" />
      </button>

      {open && (
        <div className="account-menu" role="menu">
          <NavLink to="/account" className="account-menu-item" onClick={() => setOpen(false)}>
            <Icon name="user" size={14} />
            Your account
          </NavLink>

          <div className="account-menu-label">Theme</div>
          <div className="segmented">
            {themes.map((option) => (
              <button
                key={option.value}
                className="segmented-option"
                aria-selected={theme === option.value}
                onClick={() => dispatch(themeSet(option.value))}
                title={option.label}
              >
                <Icon name={option.icon} size={13} />
                {option.label}
              </button>
            ))}
          </div>

          <div className="account-menu-rule" />
          <button className="account-menu-item danger" onClick={() => void signOut()}>
            <Icon name="logout" size={14} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
