// src/bootstrap/http401.ts
// Centralized 401 handling for fetch and axios.
// On 401, remembers the current URL and redirects to /login.
//
// This file is imported once at app bootstrap (see index.tsx).

import axios from "axios";

/// <reference lib="dom" />

const LOGIN_PATH_PREFIX = "/login";
const ENABLE_SILENT_REFRESH = false;          // flip true if you add a refresh endpoint
const REFRESH_ENDPOINT = "/auth/refresh";     // POST to refresh access token (httpOnly cookie)
const INCLUDE_CREDENTIALS_DEFAULT = "include" as const;

const STATUS_401_ALLOWLIST: RegExp[] = [
  // /^\/api\/public-check/,
];

declare global {
  interface Window {
    __http401Installed__?: boolean;
  }
}

if (!window.__http401Installed__) {
  window.__http401Installed__ = true;
  // eslint-disable-next-line no-console
  console.debug("[http401] installed");

  // ─── Helpers ──────────────────────────────────────────────
  const isOnLoginPage = (): boolean =>
    location.pathname.startsWith(LOGIN_PATH_PREFIX);

  const isAllowlisted = (url: string): boolean =>
    STATUS_401_ALLOWLIST.some((rx) => rx.test(url));

  const rememberReturnUrl = (): void => {
    try {
      sessionStorage.setItem("next", location.pathname + location.search);
    } catch {
      /* ignore */
    }
  };

  let sessionExpiryHandled = false;

  const handleSessionExpiryOnce = (): void => {
    if (sessionExpiryHandled || isOnLoginPage()) return;
    sessionExpiryHandled = true;

    rememberReturnUrl();

    // Hard redirect so all state is cleared; your normal /login + PLEX
    // banner flow handles the UI.
    window.location.href = LOGIN_PATH_PREFIX;
  };

  // ─── Optional: single-flight silent refresh ───────────────
  let refreshInFlight: Promise<Response> | null = null;

  const attemptSilentRefresh = async (): Promise<boolean> => {
    if (!ENABLE_SILENT_REFRESH) return false;
    try {
      if (!refreshInFlight) {
        refreshInFlight = fetch(REFRESH_ENDPOINT, {
          method: "POST",
          credentials: "include",
        });
      }
      const resp = await refreshInFlight;
      refreshInFlight = null;
      return resp.ok;
    } catch {
      refreshInFlight = null;
      return false;
    }
  };

  // ─── fetch patch ──────────────────────────────────────────
  const nativeFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
        ? input.pathname + input.search
        : input.url;

    const response = await nativeFetch(input, {
      credentials: init.credentials ?? INCLUDE_CREDENTIALS_DEFAULT,
      ...init,
    });

    if (
      response.status === 401 &&
      !isOnLoginPage() &&
      !isAllowlisted(requestUrl)
    ) {
      if (!(await attemptSilentRefresh())) {
        handleSessionExpiryOnce();
      } else {
        // retry once after successful refresh
        return nativeFetch(input, {
          credentials: init.credentials ?? INCLUDE_CREDENTIALS_DEFAULT,
          ...init,
        });
      }
    }

    return response;
  };

  // ─── axios interceptor (all axios calls) ───────────────────
  const attachAxiosInterceptor = (ax: typeof axios | any): void => {
    if (!ax?.interceptors?.response?.use) return;

    ax.interceptors.response.use(
      (ok: unknown) => ok,
      async (error: any) => {
        const status = error?.response?.status as number | undefined;
        const url: string =
          error?.config?.url ?? error?.response?.config?.url ?? "";

        if (status === 401 && !isOnLoginPage() && !isAllowlisted(url)) {
          if (ENABLE_SILENT_REFRESH && !error.config?._retry) {
            error.config._retry = true;
            const refreshed = await attemptSilentRefresh();
            if (refreshed) {
              return ax(error.config);
            }
          }
          handleSessionExpiryOnce();
        }

        return Promise.reject(error);
      }
    );
  };

  attachAxiosInterceptor(axios);
}

export {};
