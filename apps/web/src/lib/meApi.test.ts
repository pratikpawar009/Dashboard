import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchMe } from "@/lib/meApi";
import type { MeData } from "@/types/me";

/**
 * `meApi.ts` tests (T-04) -- OVW-05-FR-3 status-mapping coverage:
 * ok / forbidden(403) / unauthorized(401) / error (non-ok status + network
 * throw). No `overviewApi.test.ts` or `programDetailApi.test.ts` exists yet
 * to mirror directly, so the `Response`-based `global.fetch` mocking style
 * follows `tokenStore.test.ts` (the closest existing fetch-wrapper test
 * precedent in this codebase).
 */

function meResponseBody(overrides?: Partial<MeData>): string {
  return JSON.stringify({
    name: "Ada Lovelace",
    persona: "architect",
    ...overrides,
  });
}

describe("fetchMe (T-04)", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function getFetchMock(): ReturnType<typeof vi.fn> {
    return global.fetch as ReturnType<typeof vi.fn>;
  }

  it("returns {status: 'ok', data} on a 200 response, parsing the frozen {name, persona} shape", async () => {
    getFetchMock().mockResolvedValueOnce(
      new Response(meResponseBody(), { status: 200 }),
    );

    const result = await fetchMe({ accessToken: "token-abc" });

    expect(result).toEqual({
      status: "ok",
      data: { name: "Ada Lovelace", persona: "architect" },
    });
  });

  it("returns {status: 'ok', data: {name: null, ...}} for a dev-bypass token carrying no profile claims", async () => {
    getFetchMock().mockResolvedValueOnce(
      new Response(meResponseBody({ name: null }), { status: 200 }),
    );

    const result = await fetchMe();

    expect(result).toEqual({
      status: "ok",
      data: { name: null, persona: "architect" },
    });
  });

  it("maps 403 to {status: 'forbidden'}, checked before the 401 branch", async () => {
    getFetchMock().mockResolvedValueOnce(
      new Response("Access denied", { status: 403 }),
    );

    const result = await fetchMe();

    expect(result).toEqual({ status: "forbidden" });
  });

  it("maps 401 to {status: 'unauthorized'}", async () => {
    getFetchMock().mockResolvedValueOnce(
      new Response("unauthorized", { status: 401 }),
    );

    const result = await fetchMe();

    expect(result).toEqual({ status: "unauthorized" });
  });

  it("maps any other non-ok status to {status: 'error'}, never leaking the raw upstream body", async () => {
    getFetchMock().mockResolvedValueOnce(
      new Response("server_error", { status: 500 }),
    );

    const result = await fetchMe();

    expect(result).toEqual({ status: "error" });
  });

  it("maps a network/timeout throw to {status: 'error'}", async () => {
    getFetchMock().mockRejectedValueOnce(new Error("network down"));

    const result = await fetchMe();

    expect(result).toEqual({ status: "error" });
  });

  it("attaches Authorization: Bearer <token> only when accessToken is provided", async () => {
    getFetchMock().mockResolvedValueOnce(
      new Response(meResponseBody(), { status: 200 }),
    );

    await fetchMe({ accessToken: "token-xyz" });

    const [url, options] = getFetchMock().mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toContain("/api/me");
    expect((options.headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer token-xyz",
    );
  });

  it("omits the Authorization header entirely when no accessToken is provided", async () => {
    getFetchMock().mockResolvedValueOnce(
      new Response(meResponseBody(), { status: 200 }),
    );

    await fetchMe();

    const [, options] = getFetchMock().mock.calls[0] as [string, RequestInit];
    expect(
      (options.headers as Record<string, string>)["Authorization"],
    ).toBeUndefined();
  });

  it("passes an AbortSignal for the 5000ms fetch timeout", async () => {
    getFetchMock().mockResolvedValueOnce(
      new Response(meResponseBody(), { status: 200 }),
    );

    await fetchMe();

    const [, options] = getFetchMock().mock.calls[0] as [string, RequestInit];
    expect(options.signal).toBeInstanceOf(AbortSignal);
  });
});
