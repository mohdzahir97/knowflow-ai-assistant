/**
 * UI primitives.
 *
 * Thin wrappers over real elements: a `Button` is a `<button>` with classes,
 * not a re-implementation. That keeps native behaviour - form submission,
 * focus, disabled semantics - and means the styles in `styles/components.css`
 * remain the single source of visual truth.
 */
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { errorDetails, errorMessage } from "../../api/baseQuery";
import { Icon, type IconName } from "./Icon";

export { Icon };
export type { IconName };

/* --- Button ------------------------------------------------------------ */

type ButtonVariant = "default" | "primary" | "danger" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  block?: boolean;
  icon?: IconName;
  /** Shows a spinner and disables the button. */
  loading?: boolean;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  default: "",
  primary: "btn-primary",
  danger: "btn-danger",
  ghost: "btn-ghost",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", block, icon, loading, children, className, ...rest },
  ref,
) {
  const classes = [
    "btn",
    VARIANT_CLASS[variant],
    size === "sm" ? "btn-sm" : size === "lg" ? "btn-lg" : "",
    block ? "btn-block" : "",
    children === undefined ? "btn-icon" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button ref={ref} className={classes} disabled={rest.disabled || loading} {...rest}>
      {loading ? <span className="spinner" /> : icon ? <Icon name={icon} /> : null}
      {children}
    </button>
  );
});

/** An icon-only button. `label` is required, since there is no visible text. */
export function IconButton({
  icon,
  label,
  ...rest
}: { icon: IconName; label: string } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <Button variant="ghost" size="sm" icon={icon} aria-label={label} title={label} {...rest} />;
}

/* --- Field wrapper ----------------------------------------------------- */

interface FieldProps {
  label?: string;
  hint?: string;
  error?: string;
  children: (id: string) => ReactNode;
}

/**
 * Labels a control and wires the `for`/`id` pair.
 *
 * Takes a render function so the generated id reaches the input without every
 * caller having to invent one - an unlabelled control is invisible to a
 * screen reader.
 */
export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  return (
    <div className="field">
      {label && (
        <label className="field-label" htmlFor={id}>
          {label}
        </label>
      )}
      {children(id)}
      {hint && !error && <span className="field-hint">{hint}</span>}
      {error && <span className="field-error">{error}</span>}
    </div>
  );
}

/* --- Inputs ------------------------------------------------------------ */

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={["input", className ?? ""].join(" ").trim()} {...rest} />;
  },
);

/** A select with a drawn chevron, since the native arrow cannot be themed. */
export function Select({
  className,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="select-wrap">
      <select className={["select", className ?? ""].join(" ").trim()} {...rest}>
        {children}
      </select>
      <Icon name="chevronDown" className="icon-chevron" size={14} />
    </div>
  );
}

/** A textarea that grows with its content, up to the CSS max-height. */
export const AutoTextarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function AutoTextarea({ className, value, ...rest }, ref) {
  const inner = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const node = inner.current;
    if (!node) return;
    // Reset first: without this the height only ever ratchets upwards as
    // scrollHeight never shrinks below the current height.
    node.style.height = "auto";
    node.style.height = node.scrollHeight + "px";
  }, [value]);

  return (
    <textarea
      ref={(node) => {
        inner.current = node;
        if (typeof ref === "function") ref(node);
        else if (ref) ref.current = node;
      }}
      className={["textarea", className ?? ""].join(" ").trim()}
      value={value}
      {...rest}
    />
  );
});

/* --- Card -------------------------------------------------------------- */

export function Card({
  title,
  subtitle,
  actions,
  tight,
  children,
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  tight?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={"card" + (tight ? " card-tight" : "")}>
      {(title || actions) && (
        <div className="card-header">
          <div style={{ minWidth: 0 }}>
            {title && <div className="card-title">{title}</div>}
            {subtitle && <div className="card-sub">{subtitle}</div>}
          </div>
          <div className="spacer" />
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

/* --- Alert ------------------------------------------------------------- */

export type AlertKind = "info" | "success" | "warning" | "error";

const ALERT_ICON: Record<AlertKind, IconName> = {
  info: "info",
  success: "success",
  warning: "warning",
  error: "error",
};

export function Alert({ kind = "info", children }: { kind?: AlertKind; children: ReactNode }) {
  if (!children) return null;
  return (
    <div className={"alert alert-" + kind} role={kind === "error" ? "alert" : "status"}>
      <Icon name={ALERT_ICON[kind]} className="alert-icon" />
      <div className="alert-body">{children}</div>
    </div>
  );
}

/** Renders any RTK Query error, including per-field validation details. */
export function ErrorAlert({ error }: { error: unknown }) {
  const message = errorMessage(error);
  if (!message) return null;
  const details = errorDetails(error);
  return (
    <Alert kind="error">
      <div>{message}</div>
      {details.length > 0 && (
        <ul>
          {details.map((detail) => (
            <li key={detail}>{detail}</li>
          ))}
        </ul>
      )}
    </Alert>
  );
}

/* --- Badge ------------------------------------------------------------- */

export function Badge({
  tone = "neutral",
  icon,
  children,
}: {
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
  icon?: IconName;
  children: ReactNode;
}) {
  const toneClass = tone === "neutral" ? "" : "badge-" + tone;
  return (
    <span className={["badge", toneClass].join(" ").trim()}>
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}

/* --- Tabs -------------------------------------------------------------- */

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: readonly T[];
  active: T;
  onChange: (tab: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab}
          type="button"
          role="tab"
          className="tab"
          aria-selected={tab === active}
          onClick={() => onChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

/* --- Metric ------------------------------------------------------------ */

export function Metric({
  label,
  value,
  icon,
  attention,
}: {
  label: string;
  value: string | number;
  icon?: IconName;
  /** Colours the value, for a figure that means something is wrong. */
  attention?: boolean;
}) {
  return (
    <div className={"metric" + (attention ? " metric-attention" : "")}>
      <div className="metric-label">
        {icon && <Icon name={icon} size={12} />}
        {label}
      </div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

/* --- Empty state ------------------------------------------------------- */

export function EmptyState({
  icon = "info",
  title,
  body,
  action,
}: {
  icon?: IconName;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={20} />
      </div>
      <div className="empty-title">{title}</div>
      {body && <div className="empty-body">{body}</div>}
      {action}
    </div>
  );
}

/* --- Skeleton ---------------------------------------------------------- */

export function Skeleton({ height = 16, width }: { height?: number; width?: number | string }) {
  return (
    <div
      className="skeleton"
      style={{ height, width: width ?? "100%" }}
      aria-hidden="true"
    />
  );
}

/** A placeholder shaped like the content it stands in for. */
export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack-sm" aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} height={index === 0 ? 20 : 16} width={index === 0 ? "40%" : "100%"} />
      ))}
    </div>
  );
}

/* --- Copy button ------------------------------------------------------- */

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // The Clipboard API needs a secure context, so it is unavailable over
      // plain HTTP on anything but localhost. Fall back rather than failing.
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }
    setCopied(true);
    timer.current = window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <Button variant="ghost" size="sm" icon={copied ? "check" : "copy"} onClick={copy}>
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

/* --- Confirm dialog ---------------------------------------------------- */

/**
 * A modal confirmation for destructive actions.
 *
 * Used instead of `window.confirm` so the wording can explain consequences -
 * clearing the knowledge base affects every user, which a browser dialog
 * cannot convey.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  destructive,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      // A click on the backdrop cancels; a click inside must not bubble out
      // and dismiss the dialog the user is filling in.
      onClick={onCancel}
    >
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="dialog-title">{title}</div>
        <div className="secondary">{body}</div>
        <div className="dialog-actions">
          <Button onClick={onCancel}>Cancel</Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            loading={busy}
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* --- Timestamp --------------------------------------------------------- */

export function Timestamp({ value, relative }: { value: string; relative?: boolean }) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return <span>{value}</span>;

  const absolute = parsed.toLocaleString();
  return (
    <time dateTime={parsed.toISOString()} title={absolute}>
      {relative ? formatRelative(parsed) : absolute}
    </time>
  );
}

/** "3 minutes ago", falling back to a date beyond a week. */
function formatRelative(date: Date): string {
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return minutes + (minutes === 1 ? " minute ago" : " minutes ago");
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours + (hours === 1 ? " hour ago" : " hours ago");
  const days = Math.round(hours / 24);
  if (days < 7) return days + (days === 1 ? " day ago" : " days ago");
  return date.toLocaleDateString();
}
