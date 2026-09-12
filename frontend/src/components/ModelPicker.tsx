/**
 * Model selection.
 *
 * Collapsed to a single trigger showing what is currently in use, because
 * this is a set-once-and-forget choice: four permanently-expanded dropdowns
 * dominated a sidebar whose actual job is navigating conversations.
 *
 * Inside, the provider comes first and the model list follows from it. A flat
 * list of every provider's models is a long scroll padded with models you
 * cannot use, and it buries the question actually being asked - which
 * provider, then which of its models. "All" remains available for browsing,
 * and search always spans every provider so a model can be found without
 * knowing who serves it.
 *
 * Three things it does that the previous selects did not:
 *
 * 1. **Refuses unconfigured providers.** A provider with no API key on the
 *    server was previously selectable, and the failure only surfaced when
 *    the user asked a question. Here it is visibly disabled with the reason.
 * 2. **Searchable**, since a catalogue an administrator has extended can hold
 *    far more models than a dropdown comfortably shows.
 * 3. **Keyboard operable** - arrows move, Enter picks, Escape closes and
 *    returns focus to the trigger.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { useGetChatProvidersQuery, useGetEmbeddingProvidersQuery } from "../api/apiSlice";
import type { ProviderInfo } from "../api/types";
import { useAppDispatch, useAppSelector } from "../store/hooks";
import {
  chatModelSelected,
  chatProviderSelected,
  embeddingModelSelected,
  embeddingProviderSelected,
} from "../store/modelsSlice";
import { Badge, Icon } from "./ui";

type Kind = "chat" | "embedding";

/** Sentinel for the "browse everything" chip. */
export const ALL_PROVIDERS = "__all__";

/** One selectable row, flattened from the provider list. */
export interface Option {
  provider: string;
  providerLabel: string;
  model: string;
  configured: boolean;
}

export function flatten(providers: ProviderInfo[]): Option[] {
  return providers.flatMap((provider) =>
    provider.models.map((model) => ({
      provider: provider.provider,
      providerLabel: provider.display_name,
      model,
      configured: provider.is_configured,
    })),
  );
}

/** Matches on model name or provider label, case-insensitively. */
export function filterOptions(options: Option[], search: string): Option[] {
  const term = search.trim().toLowerCase();
  if (!term) return options;
  return options.filter(
    (option) =>
      option.model.toLowerCase().includes(term) ||
      option.providerLabel.toLowerCase().includes(term),
  );
}

/**
 * Narrows to one provider, unless browsing everything.
 *
 * A search overrides the provider chip: typing means "find me this model",
 * and silently hiding a match because it belongs to another provider would
 * make the search look broken.
 */
export function visibleOptions(options: Option[], provider: string, search: string): Option[] {
  const searched = filterOptions(options, search);
  if (search.trim() || provider === ALL_PROVIDERS) return searched;
  return searched.filter((option) => option.provider === provider);
}

/** Groups while preserving the filtered order, so search results stay ranked. */
export function groupByProvider(options: Option[]): [string, Option[]][] {
  const groups = new Map<string, Option[]>();
  for (const option of options) {
    const existing = groups.get(option.providerLabel);
    if (existing) existing.push(option);
    else groups.set(option.providerLabel, [option]);
  }
  return [...groups.entries()];
}

export default function ModelPicker({ isAdmin }: { isAdmin: boolean }) {
  const dispatch = useAppDispatch();
  const selection = useAppSelector((state) => state.models);
  const chatQuery = useGetChatProvidersQuery();
  const embeddingQuery = useGetEmbeddingProvidersQuery();

  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<Kind>("chat");
  const [search, setSearch] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [providerFilter, setProviderFilter] = useState<string>(ALL_PROVIDERS);

  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const providers = useMemo(
    () => (kind === "chat" ? chatQuery.data : embeddingQuery.data) ?? [],
    [kind, chatQuery.data, embeddingQuery.data],
  );
  const options = useMemo(() => flatten(providers), [providers]);

  const currentProvider = kind === "chat" ? selection.chatProvider : selection.embeddingProvider;
  const currentModel = kind === "chat" ? selection.chatModel : selection.embeddingModel;

  const visible = useMemo(
    () => visibleOptions(options, providerFilter, search),
    [options, providerFilter, search],
  );

  const isCurrent = (option: Option) =>
    option.provider === currentProvider && option.model === currentModel;

  // Close on an outside click or Escape, and hand focus back to the trigger -
  // otherwise keyboard users are dropped at the top of the document.
  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // Opening starts on the provider already in use, so its models are the
  // first thing shown rather than a wall of every provider's catalogue.
  useEffect(() => {
    if (open) {
      setProviderFilter(currentProvider || ALL_PROVIDERS);
      searchRef.current?.focus();
    } else {
      setSearch("");
      setKind("chat");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Switching between Chat and Embeddings re-anchors on that kind's provider.
  useEffect(() => {
    if (open) setProviderFilter(currentProvider || ALL_PROVIDERS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  // Keep the highlight on the current model when the list changes under it.
  useEffect(() => {
    const index = visible.findIndex(isCurrent);
    setActiveIndex(index >= 0 ? index : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible.length, providerFilter, kind]);

  const choose = (option: Option) => {
    if (!option.configured) return;
    if (kind === "chat") {
      if (option.provider !== selection.chatProvider) dispatch(chatProviderSelected(option.provider));
      dispatch(chatModelSelected(option.model));
    } else {
      if (option.provider !== selection.embeddingProvider) {
        dispatch(embeddingProviderSelected(option.provider));
      }
      dispatch(embeddingModelSelected(option.model));
    }
    setOpen(false);
    triggerRef.current?.focus();
  };

  const onListKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (visible.length === 0) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((index) => (index + step + visible.length) % visible.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = visible[activeIndex];
      if (option) choose(option);
    }
  };

  const activeProviderInfo = (chatQuery.data ?? []).find(
    (provider) => provider.provider === selection.chatProvider,
  );
  const chatUnconfigured = activeProviderInfo !== undefined && !activeProviderInfo.is_configured;
  const searching = search.trim() !== "";

  return (
    <div className="model-picker">
      <button
        ref={triggerRef}
        className={"model-trigger" + (open ? " open" : "")}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <Icon name="sparkles" size={14} />
        <span className="model-trigger-text">
          <span className="model-trigger-label">
            {selection.chatProvider || "Model"}
          </span>
          <span className="model-trigger-value truncate">
            {selection.chatModel || "Not selected"}
          </span>
        </span>
        {chatUnconfigured && (
          <Icon name="warning" size={14} style={{ color: "var(--warning)", flex: "0 0 auto" }} />
        )}
        <Icon name="chevronDown" size={14} className="model-trigger-chevron" />
      </button>

      {open && (
        <div className="model-panel" ref={panelRef} role="dialog" aria-label="Choose a model">
          {/* Embedding choice decides which knowledge-base partition is
              searched - an operational concern an end user should not have
              to think about, so the tabs only appear for an administrator. */}
          {isAdmin && (
            <div className="segmented" role="tablist">
              {(["chat", "embedding"] as const).map((value) => (
                <button
                  key={value}
                  role="tab"
                  aria-selected={kind === value}
                  className="segmented-option"
                  onClick={() => setKind(value)}
                >
                  {value === "chat" ? "Chat" : "Embeddings"}
                </button>
              ))}
            </div>
          )}

          <div className="provider-chips" role="tablist" aria-label="Provider">
            <button
              role="tab"
              aria-selected={providerFilter === ALL_PROVIDERS && !searching}
              className="provider-chip"
              onClick={() => setProviderFilter(ALL_PROVIDERS)}
            >
              All
              <span className="provider-chip-count">{options.length}</span>
            </button>
            {providers.map((provider) => (
              <button
                key={provider.provider}
                role="tab"
                aria-selected={providerFilter === provider.provider && !searching}
                className={"provider-chip" + (provider.is_configured ? "" : " unconfigured")}
                onClick={() => setProviderFilter(provider.provider)}
                title={
                  provider.is_configured
                    ? provider.display_name
                    : provider.display_name + " has no API key configured on the server."
                }
              >
                {provider.display_name}
                <span className="provider-chip-count">{provider.models.length}</span>
              </button>
            ))}
          </div>

          <div className="model-search">
            <Icon name="search" size={14} />
            <input
              ref={searchRef}
              value={search}
              placeholder="Search all providers..."
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={onListKeyDown}
              aria-label="Search models"
            />
            {searching && (
              <button
                className="model-search-clear"
                onClick={() => setSearch("")}
                aria-label="Clear search"
              >
                <Icon name="close" size={12} />
              </button>
            )}
          </div>

          <div className="model-list" onKeyDown={onListKeyDown} role="listbox" tabIndex={-1}>
            {visible.length === 0 && (
              <div className="model-empty">
                {options.length === 0
                  ? "No models are configured. An administrator can add them under Administration."
                  : "Nothing matches that search."}
              </div>
            )}

            {groupByProvider(visible).map(([providerLabel, group]) => (
              <div key={providerLabel} className="model-group">
                {/* The heading is redundant when the list is already one
                    provider's models, and useful when it is not. */}
                {(searching || providerFilter === ALL_PROVIDERS) && (
                  <div className="model-group-label">
                    {providerLabel}
                    {!group[0]!.configured && <Badge tone="warning">No API key</Badge>}
                  </div>
                )}
                {group.map((option) => {
                  const index = visible.indexOf(option);
                  return (
                    <button
                      key={option.provider + "/" + option.model}
                      role="option"
                      aria-selected={isCurrent(option)}
                      className={
                        "model-option" +
                        (index === activeIndex ? " active" : "") +
                        (option.configured ? "" : " disabled")
                      }
                      disabled={!option.configured}
                      title={
                        option.configured
                          ? option.model
                          : "This provider has no API key configured on the server."
                      }
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => choose(option)}
                    >
                      <span className="truncate">{option.model}</span>
                      {isCurrent(option) && <Icon name="check" size={14} />}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>

          <div className="model-panel-footer">
            {!providers.some((provider) => provider.is_configured) ? (
              <span style={{ color: "var(--warning)" }}>
                No provider has an API key on the server, so nothing can be selected.
              </span>
            ) : kind === "chat" ? (
              <>Answers are generated with this model.</>
            ) : (
              <>Documents are indexed with this model. Changing it changes what is searched.</>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
