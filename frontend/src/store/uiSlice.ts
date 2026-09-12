/**
 * Presentation state: theme, transient notifications, and the mobile drawer.
 *
 * In the store rather than in component state because all three are read or
 * written from places that do not share a parent - the theme toggle lives in
 * the sidebar but applies to the document, and a mutation on one page raises a
 * toast rendered by a host at the root.
 */
import { createSlice, nanoid, type PayloadAction } from "@reduxjs/toolkit";

const THEME_KEY = "aika.theme";

/** "system" follows the OS; the other two override it in both directions. */
export type ThemePreference = "system" | "light" | "dark";

export interface Toast {
  id: string;
  kind: "success" | "error" | "info";
  message: string;
}

interface UiState {
  theme: ThemePreference;
  toasts: Toast[];
  sidebarOpen: boolean;
}

function readStoredTheme(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

const initialState: UiState = {
  theme: readStoredTheme(),
  toasts: [],
  sidebarOpen: false,
};

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    themeSet(state, action: PayloadAction<ThemePreference>) {
      state.theme = action.payload;
      try {
        if (action.payload === "system") localStorage.removeItem(THEME_KEY);
        else localStorage.setItem(THEME_KEY, action.payload);
      } catch {
        /* the choice simply will not persist */
      }
    },
    toastRaised: {
      reducer(state, action: PayloadAction<Toast>) {
        // Bounded: a burst of failures should not stack a wall of cards over
        // the UI.
        state.toasts = [...state.toasts, action.payload].slice(-3);
      },
      prepare(kind: Toast["kind"], message: string) {
        return { payload: { id: nanoid(), kind, message } };
      },
    },
    toastDismissed(state, action: PayloadAction<string>) {
      state.toasts = state.toasts.filter((toast) => toast.id !== action.payload);
    },
    sidebarToggled(state) {
      state.sidebarOpen = !state.sidebarOpen;
    },
    sidebarClosed(state) {
      state.sidebarOpen = false;
    },
  },
});

export const { themeSet, toastRaised, toastDismissed, sidebarToggled, sidebarClosed } =
  uiSlice.actions;
export default uiSlice.reducer;
