/**
 * The base query every endpoint runs through.
 *
 * It does two things `fetchBaseQuery` cannot do alone:
 *
 * 1. **Unwraps the response envelope.** The API always replies
 *    `{success, message, data, errors}`. Unwrapping here means endpoints are
 *    typed as the payload they actually return, instead of every component
 *    reaching through `.data.data`. A `success: false` body is turned into an
 *    error even when the status is 2xx, so a failure can never be mistaken
 *    for data.
 *
 * 2. **Refreshes an expired access token once, not once per request.** The
 *    backend rotates and revokes the refresh token on use, so several
 *    concurrent 401s must not each try to refresh: the first would succeed
 *    and the rest would present a token that had just been revoked, signing
 *    the user out mid page load.
 */
import type { BaseQueryFn, FetchArgs, FetchBaseQueryError } from "@reduxjs/toolkit/query";
import { fetchBaseQuery } from "@reduxjs/toolkit/query";

import type { RootState } from "../store";
import { sessionEnded, tokensReceived } from "../store/authSlice";
import type { ApiEnvelope, TokenPair } from "./types";

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8001";

const rawBaseQuery = fetchBaseQuery({
  baseUrl: API_BASE_URL,
  prepareHeaders: (headers, { getState }) => {
    const token = (getState() as RootState).auth.accessToken;
    if (token) headers.set("Authorization", "Bearer " + token);
    return headers;
  },
});

/** Pulls a human-readable message out of whatever the server returned. */
function describe(error: FetchBaseQueryError): { message: string; details: string[] } {
  if (typeof error.status === "number") {
    const body = error.data as ApiEnvelope<unknown> | undefined;
    if (body && typeof body === "object" && "message" in body) {
      return { message: String(body.message), details: body.errors ?? [] };
    }
    return { message: "Request failed with status " + error.status + ".", details: [] };
  }
  if (error.status === "FETCH_ERROR") {
    return {
      message: "Could not reach the backend at " + API_BASE_URL + ". " + error.error,
      details: [],
    };
  }
  if (error.status === "PARSING_ERROR") {
    return { message: "The server returned an unexpected response.", details: [] };
  }
  return { message: "error" in error ? String(error.error) : "Request failed.", details: [] };
}

/**
 * What the envelope said, carried alongside the unwrapped payload.
 *
 * Needed because a 2xx can still report partial failure: uploading three PDFs
 * where one is unreadable returns 201, `success: true`, the two good
 * documents in `data`, and the failure in `errors`. Dropping `errors` on
 * success would report "2 documents indexed" and never mention the third.
 */
export interface EnvelopeMeta {
  message: string;
  errors: string[];
}

/** The shape components read errors from, whatever went wrong. */
export interface AppError {
  status: number | string;
  message: string;
  details: string[];
}

function toAppError(error: FetchBaseQueryError): AppError {
  const { message, details } = describe(error);
  return { status: error.status, message, details };
}

let refreshInFlight: Promise<boolean> | null = null;

/**
 * Exchanges the stored refresh token for a new pair. At most one at a time.
 *
 * Exported because the answer stream cannot go through RTK Query - it needs a
 * partial response body - but must still recover from an expired access
 * token. Both callers share this one promise, so a stream starting at the
 * same moment as a query cannot trigger two refreshes and have the second
 * present a token the first has already caused to be revoked.
 */
export function refreshSession(
  dispatch: (action: { type: string; payload?: unknown }) => void,
  refreshToken: string | null,
): Promise<boolean> {
  if (!refreshToken) return Promise.resolve(false);
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const response = await fetch(API_BASE_URL + "/api/v1/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) {
        // Only an explicit rejection ends the session. A network failure
        // leaves the stored token alone so a brief outage does not sign
        // everyone out.
        if (response.status >= 400 && response.status < 500) dispatch(sessionEnded());
        return false;
      }

      const envelope = (await response.json()) as ApiEnvelope<TokenPair>;
      if (!envelope?.success) {
        dispatch(sessionEnded());
        return false;
      }
      dispatch(tokensReceived(envelope.data));
      return true;
    } catch {
      // Network-level failure: keep the session.
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

export const baseQueryWithReauth: BaseQueryFn<string | FetchArgs, unknown, AppError> = async (
  args,
  apiContext,
  extraOptions,
) => {
  const run = async () => rawBaseQuery(args, apiContext, extraOptions);

  let result = await run();

  const isUnauthorised = result.error && result.error.status === 401;
  const state = apiContext.getState() as RootState;

  // No stored refresh token means there is no session to repair - a failed
  // login must not trigger a refresh attempt.
  if (isUnauthorised && state.auth.refreshToken) {
    const refreshed = await refreshSession(
      apiContext.dispatch as (action: { type: string; payload?: unknown }) => void,
      state.auth.refreshToken,
    );
    if (refreshed) {
      // prepareHeaders re-reads the store, so the retry carries the new token.
      result = await run();
    }
  }

  if (result.error) return { error: toAppError(result.error) };

  // A 2xx envelope can still report failure; treat that as an error so no
  // component has to check `success` itself.
  const envelope = result.data as ApiEnvelope<unknown> | undefined;
  if (envelope && typeof envelope === "object" && "success" in envelope) {
    if (!envelope.success) {
      return {
        error: {
          status: 200,
          message: envelope.message ?? "Request failed.",
          details: envelope.errors ?? [],
        },
      };
    }
    const envelopeMeta: EnvelopeMeta = {
      message: envelope.message ?? "",
      errors: envelope.errors ?? [],
    };
    return { data: envelope.data, meta: { ...result.meta, envelope: envelopeMeta } };
  }

  // Endpoints outside the envelope convention, such as /health.
  return { data: result.data, meta: result.meta };
};

/** Formats an error for display, whatever its origin. */
export function errorMessage(error: unknown): string | null {
  if (!error) return null;
  if (typeof error === "object" && error !== null && "message" in error) {
    return String((error as AppError).message);
  }
  if (error instanceof Error) return error.message;
  return String(error);
}

export function errorDetails(error: unknown): string[] {
  if (typeof error === "object" && error !== null && "details" in error) {
    return (error as AppError).details ?? [];
  }
  return [];
}
