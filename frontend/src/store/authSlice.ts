/**
 * Session tokens.
 *
 * Only tokens live here. The signed-in profile is an RTK Query cache entry, so
 * there is one source of truth for it and it invalidates like any other server
 * data (confirming an email address updates it automatically).
 *
 * The access token is held in memory. Just the refresh token is mirrored into
 * localStorage, so closing the tab does not destroy the session while a stolen
 * localStorage snapshot yields a credential the server can revoke. A cookie
 * scheme would resist XSS better; it would also need CSRF protection, which
 * the API deliberately does not implement because nothing authenticates from a
 * cookie today.
 */
import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

import type { TokenPair } from "../api/types";

const REFRESH_TOKEN_KEY = "aika.refresh_token";

export function readStoredRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  } catch {
    // Private mode, or a browser set to block site data.
    return null;
  }
}

function writeStoredRefreshToken(token: string | null): void {
  try {
    if (token === null) localStorage.removeItem(REFRESH_TOKEN_KEY);
    else localStorage.setItem(REFRESH_TOKEN_KEY, token);
  } catch {
    // The session still works for this tab, it just will not survive a reload.
  }
}

export interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
}

const initialState: AuthState = {
  accessToken: null,
  refreshToken: readStoredRefreshToken(),
};

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    tokensReceived(state, action: PayloadAction<TokenPair>) {
      state.accessToken = action.payload.access_token;
      state.refreshToken = action.payload.refresh_token;
      writeStoredRefreshToken(action.payload.refresh_token);
    },
    /** The stored token was rejected, or the user signed out. */
    sessionEnded(state) {
      state.accessToken = null;
      state.refreshToken = null;
      writeStoredRefreshToken(null);
    },
  },
});

export const { tokensReceived, sessionEnded } = authSlice.actions;
export default authSlice.reducer;
