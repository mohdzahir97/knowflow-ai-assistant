/**
 * Who is signed in, and how to sign in and out.
 *
 * Restoring a session needs no special code: asking for the profile with a
 * stored refresh token but no access token produces a 401, and the base query
 * refreshes and retries. So "am I signed in?" is simply "did the profile
 * query succeed?", with no second copy of that state to keep in sync.
 */
import { useCallback } from "react";

import { apiSlice, useGetProfileQuery, useLoginMutation } from "../api/apiSlice";
import type { Profile } from "../api/types";
import { useAppDispatch, useAppSelector } from "./hooks";
import { sessionEnded, tokensReceived } from "./authSlice";
import { conversationCleared } from "./chatSlice";

export interface Session {
  profile: Profile | undefined;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /** True only while the initial restore attempt is still in flight. */
  restoring: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

export function useSession(): Session {
  const dispatch = useAppDispatch();
  const { accessToken, refreshToken } = useAppSelector((state) => state.auth);
  const [login] = useLoginMutation();

  // Nothing to ask about with no credentials at all: skipping avoids a
  // pointless 401 on the sign-in screen.
  const hasCredentials = Boolean(accessToken || refreshToken);
  const { data: profile, isLoading } = useGetProfileQuery(undefined, { skip: !hasCredentials });

  const signIn = useCallback(
    async (email: string, password: string) => {
      const tokens = await login({ email, password }).unwrap();
      // Cleared here rather than on sign-out. Either point prevents the next
      // account seeing the previous one's cached documents, chats and
      // metrics; doing it on the way in means the cache is never emptied
      // while pages are still mounted and able to refetch.
      dispatch(apiSlice.util.resetApiState());
      dispatch(tokensReceived(tokens));
    },
    [dispatch, login],
  );

  const signOut = useCallback(async () => {
    if (refreshToken) {
      // Best effort: revoking server-side is preferable, but a failure must
      // not trap the user in a session they asked to leave.
      try {
        await dispatch(apiSlice.endpoints.logout.initiate({ refresh_token: refreshToken })).unwrap();
      } catch {
        /* ignore */
      }
    }
    dispatch(sessionEnded());
    dispatch(conversationCleared());
  }, [dispatch, refreshToken]);

  return {
    profile,
    // Both halves matter. Deriving this from the profile alone let the app
    // present a signed-in UI after the tokens had been cleared - a failed
    // refresh dispatches `sessionEnded`, but the cached profile survives it,
    // so the shell stayed mounted and every request it made went out with no
    // Authorization header. The backend answers those with "Not
    // authenticated", which is what the user saw.
    isAuthenticated: hasCredentials && profile !== undefined,
    isAdmin: profile?.role === "admin",
    restoring: hasCredentials && isLoading,
    signIn,
    signOut,
  };
}
