import { type Error as APIError } from "./contracts";

export type RequestOptions = {
  method?: string;
  body?: unknown;
  revision?: number | string;
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export class PharmaAPIError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "PharmaAPIError";
  }
}

export async function pharmaFetch<T>(
  path: string,
  options: RequestOptions = {},
  csrf?: string,
): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("..")) {
    throw new Error("无效的请求路径");
  }
  const method = options.method ?? "GET";
  const headers = new Headers({ Accept: "application/json" });
  if (options.body !== undefined)
    headers.set("Content-Type", "application/json");
  if (csrf && method !== "GET") headers.set("X-CSRF-Token", csrf);
  if (options.revision !== undefined)
    headers.set("If-Match", `"${options.revision}"`);
  if (method === "POST")
    headers.set(
      "Idempotency-Key",
      options.idempotencyKey ?? crypto.randomUUID(),
    );
  const response = await fetch(`/api/pharma/v1${path}`, {
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  if (!response.ok) {
    let envelope: APIError | undefined;
    try {
      envelope = (await response.json()) as APIError;
    } catch {
      /* Proxy/network errors may be plain text. */
    }
    throw new PharmaAPIError(
      response.status,
      envelope?.error?.code ?? "HTTP_ERROR",
      envelope?.error?.message ??
        `请求未完成（${response.status}），请稍后重试`,
      envelope?.error?.request_id,
      envelope?.error?.details,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function safeSourceURL(url: string | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol === "https:" &&
      ["clinicaltrials.gov", "pubmed.ncbi.nlm.nih.gov"].includes(
        parsed.hostname,
      )
    )
      return parsed.href;
  } catch {
    /* An invalid source address is displayed as text only. */
  }
  return undefined;
}
