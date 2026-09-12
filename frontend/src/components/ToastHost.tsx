/**
 * Renders transient notifications, and applies the theme to the document.
 *
 * Both live here because both are document-level side effects of store state,
 * and neither belongs to any one page.
 */
import { useEffect } from "react";

import { useAppDispatch, useAppSelector } from "../store/hooks";
import { toastDismissed } from "../store/uiSlice";
import { Icon, IconButton } from "./ui";

const AUTO_DISMISS_MS = 4500;

export function ThemeEffect() {
  const theme = useAppSelector((state) => state.ui.theme);

  useEffect(() => {
    const root = document.documentElement;
    // "system" removes the attribute rather than setting a value, so the
    // prefers-color-scheme rules take over again.
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  return null;
}

export function ToastHost() {
  const toasts = useAppSelector((state) => state.ui.toasts);
  const dispatch = useAppDispatch();

  useEffect(() => {
    if (toasts.length === 0) return;
    // One timer per toast, keyed by id, so a new arrival does not reset the
    // countdown of the ones already showing.
    const timers = toasts.map((toast) =>
      window.setTimeout(() => dispatch(toastDismissed(toast.id)), AUTO_DISMISS_MS),
    );
    return () => timers.forEach(window.clearTimeout);
  }, [toasts, dispatch]);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-host" role="region" aria-label="Notifications">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={"toast toast-" + toast.kind}
          role={toast.kind === "error" ? "alert" : "status"}
        >
          <Icon
            name={toast.kind === "success" ? "success" : toast.kind === "error" ? "error" : "info"}
            style={{ marginTop: 2, flex: "0 0 auto" }}
          />
          <div className="toast-body">{toast.message}</div>
          <IconButton
            icon="close"
            label="Dismiss notification"
            onClick={() => dispatch(toastDismissed(toast.id))}
          />
        </div>
      ))}
    </div>
  );
}
