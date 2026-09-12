/**
 * The model picker's list logic.
 *
 * Only the pure parts are tested here - flattening, searching and grouping.
 * The panel's open/closed state is ordinary React local state and is verified
 * by using it; these are the pieces where a bug would silently show the wrong
 * models, or hide one the user needs.
 */
import { describe, expect, it } from "vitest";

import {
  ALL_PROVIDERS,
  filterOptions,
  flatten,
  groupByProvider,
  visibleOptions,
} from "./ModelPicker";
import type { ProviderInfo } from "../api/types";

const PROVIDERS: ProviderInfo[] = [
  {
    provider: "ollama",
    display_name: "Ollama",
    models: ["gemma4", "llama3.1", "mistral"],
    is_configured: true,
  },
  {
    provider: "openai",
    display_name: "OpenAI",
    models: ["gpt-4o", "gpt-4o-mini"],
    is_configured: false,
  },
];

describe("flatten", () => {
  it("produces one row per model, carrying the provider's configured state", () => {
    const options = flatten(PROVIDERS);
    expect(options).toHaveLength(5);
    expect(options[0]).toEqual({
      provider: "ollama",
      providerLabel: "Ollama",
      model: "gemma4",
      configured: true,
    });
    // An unconfigured provider's models are still listed - they are shown
    // disabled with the reason, rather than hidden, so the user can see the
    // model exists and why they cannot pick it.
    expect(options.filter((option) => !option.configured).map((o) => o.model)).toEqual([
      "gpt-4o",
      "gpt-4o-mini",
    ]);
  });

  it("handles a provider with no models", () => {
    expect(flatten([{ ...PROVIDERS[0]!, models: [] }])).toEqual([]);
  });
});

describe("filterOptions", () => {
  const options = flatten(PROVIDERS);

  it("returns everything for an empty search", () => {
    expect(filterOptions(options, "")).toHaveLength(5);
    expect(filterOptions(options, "   ")).toHaveLength(5);
  });

  it("matches on the model name", () => {
    expect(filterOptions(options, "gpt").map((o) => o.model)).toEqual(["gpt-4o", "gpt-4o-mini"]);
  });

  it("matches on the provider label, so a whole provider can be narrowed to", () => {
    expect(filterOptions(options, "ollama")).toHaveLength(3);
  });

  it("ignores case", () => {
    expect(filterOptions(options, "GEMMA")).toHaveLength(1);
    expect(filterOptions(options, "OpenAI")).toHaveLength(2);
  });

  it("returns nothing when there is no match", () => {
    expect(filterOptions(options, "does-not-exist")).toEqual([]);
  });
});

describe("groupByProvider", () => {
  it("groups rows under their provider label", () => {
    const groups = groupByProvider(flatten(PROVIDERS));
    expect(groups.map(([label]) => label)).toEqual(["Ollama", "OpenAI"]);
    expect(groups[0]![1]).toHaveLength(3);
    expect(groups[1]![1]).toHaveLength(2);
  });

  it("preserves filtered order, so search results stay ranked", () => {
    // Only OpenAI matches, so it must be the sole group even though Ollama
    // comes first in the unfiltered list.
    const groups = groupByProvider(filterOptions(flatten(PROVIDERS), "gpt"));
    expect(groups.map(([label]) => label)).toEqual(["OpenAI"]);
  });

  it("returns nothing for an empty list", () => {
    expect(groupByProvider([])).toEqual([]);
  });
});


describe("visibleOptions", () => {
  const options = flatten(PROVIDERS);

  it("shows only the chosen provider's models", () => {
    const visible = visibleOptions(options, "ollama", "");
    expect(visible.map((o) => o.model)).toEqual(["gemma4", "llama3.1", "mistral"]);
  });

  it("shows every provider under All", () => {
    expect(visibleOptions(options, ALL_PROVIDERS, "")).toHaveLength(5);
  });

  it("includes an unconfigured provider's models when it is chosen", () => {
    // Selectable is a separate question from visible: seeing the models and
    // why they cannot be used beats hiding the provider.
    const visible = visibleOptions(options, "openai", "");
    expect(visible.map((o) => o.model)).toEqual(["gpt-4o", "gpt-4o-mini"]);
    expect(visible.every((o) => !o.configured)).toBe(true);
  });

  it("lets a search reach past the chosen provider", () => {
    // Typing means "find me this model". Hiding a match because it belongs
    // to another provider would make the search look broken.
    const visible = visibleOptions(options, "ollama", "gpt");
    expect(visible.map((o) => o.model)).toEqual(["gpt-4o", "gpt-4o-mini"]);
  });

  it("returns nothing when a search matches nothing", () => {
    expect(visibleOptions(options, ALL_PROVIDERS, "nope")).toEqual([]);
  });
});
