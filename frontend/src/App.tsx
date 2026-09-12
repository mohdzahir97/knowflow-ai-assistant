/**
 * Routing and the authenticated shell.
 *
 * The reset and verify routes are declared outside the authenticated area on
 * purpose: an emailed reset link must work on a browser that is already
 * signed in, which is exactly the case where an account has been compromised.
 */
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import Sidebar from "./components/Sidebar";
import { ThemeEffect, ToastHost } from "./components/ToastHost";
import { Icon, IconButton, Skeleton } from "./components/ui";
import Account from "./pages/Account";
import Administration from "./pages/Administration";
import Chat from "./pages/Chat";
import KnowledgeBase from "./pages/KnowledgeBase";
import { ResetPasswordPage, VerifyEmailPage } from "./pages/ResetPassword";
import SignIn from "./pages/SignIn";
import { useAppDispatch, useAppSelector } from "./store/hooks";
import { useSession } from "./store/session";
import { sidebarClosed, sidebarToggled } from "./store/uiSlice";

const TITLES: Record<string, string> = {
  "/chat": "Chat",
  "/knowledge-base": "Knowledge base",
  "/administration": "Administration",
  "/account": "Your account",
};

export default function App() {
  return (
    <>
      <ThemeEffect />
      <ToastHost />
      <Routes>
        {/* Reachable signed in or out. */}
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="*" element={<Gate />} />
      </Routes>
    </>
  );
}

function Gate() {
  const { isAuthenticated, restoring } = useSession();

  if (restoring) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-head">
            <span className="brand-mark">
              <Icon name="sparkles" size={16} />
            </span>
            <div className="muted">Restoring your session</div>
          </div>
          <div className="stack-sm">
            <Skeleton height={14} width="70%" />
            <Skeleton height={14} />
            <Skeleton height={14} width="40%" />
          </div>
        </div>
      </div>
    );
  }
  return isAuthenticated ? <AuthenticatedShell /> : <SignIn />;
}

function AuthenticatedShell() {
  const { isAdmin } = useSession();
  const dispatch = useAppDispatch();
  const sidebarOpen = useAppSelector((state) => state.ui.sidebarOpen);
  const location = useLocation();

  const onChatPage = location.pathname === "/chat" || location.pathname === "/";
  const title = TITLES[location.pathname] ?? "Chat";

  return (
    <div className="shell">
      <Sidebar showChatHistory={onChatPage} />

      {/* Tapping outside the drawer closes it, which is the expected gesture
          on a phone and costs nothing on a desktop where it never renders. */}
      {sidebarOpen && (
        <div className="scrim" role="presentation" onClick={() => dispatch(sidebarClosed())} />
      )}

      <main className="main">
        <header className="topbar">
          <span className="sidebar-toggle">
            <IconButton
              icon="menu"
              label="Open menu"
              onClick={() => dispatch(sidebarToggled())}
            />
          </span>
          <h1 className="topbar-title">{title}</h1>
        </header>

        {/* Chat manages its own scrolling and pins its composer, so it opts
            out of the standard padded, scrolling page wrapper. */}
        <div className={onChatPage ? "page page-flush" : "page"}>
          <Routes>
            <Route path="/chat" element={<Chat />} />
            <Route path="/account" element={<Account />} />
            {/* Admin routes are absent for a non-admin, so a typed URL lands
                on the redirect below rather than rendering a page whose
                requests would all be refused. */}
            {isAdmin && <Route path="/knowledge-base" element={<KnowledgeBase />} />}
            {isAdmin && <Route path="/administration" element={<Administration />} />}
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
