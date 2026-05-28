/**
 * Unified API error parser (v2.12-WP09 / E1).
 *
 * The backend now emits a single error-envelope shape across every
 * route:
 *
 *     { "error": { "code": "...", "message": "...",
 *                  "correlation_id": "..." | null,
 *                  "details": {...} | null } }
 *
 * For a transitional period this adapter ALSO accepts the legacy
 * ``{ "detail": "..." }`` shape (FastAPI's pre-WP09 default) so older
 * tests and any non-migrated paths continue to surface a useful
 * message. Permissive by design — additive only, no sweeping rewrite.
 */

export interface ParsedApiError {
  /** Machine-stable code from the unified envelope, or a synthetic
   *  ``"http_error"`` / ``"unknown"`` placeholder for legacy bodies. */
  code: string;
  /** Human-readable message — safe to surface to end users. */
  message: string;
  /** Correlation id from the envelope; ``null`` when absent or when
   *  parsing a legacy ``{detail}`` body. */
  correlation_id: string | null;
  /** Structured detail payload from the envelope (may be ``null``).
   *  Callers that need the legacy ``next_allowed_at`` etc. can read
   *  it from here. */
  details: unknown;
  /** Original HTTP status (when a ``Response`` is supplied). */
  status: number;
}

interface UnifiedEnvelopeShape {
  error: {
    code: string;
    message: string;
    correlation_id?: string | null;
    details?: unknown;
  };
}

interface LegacyDetailShape {
  detail?: unknown;
  // Some legacy paths used to nest extra fields alongside ``detail``;
  // surface them through ``details`` so the caller can read them.
  [k: string]: unknown;
}

function isUnifiedEnvelope(body: unknown): body is UnifiedEnvelopeShape {
  return (
    !!body &&
    typeof body === "object" &&
    "error" in body &&
    typeof (body as { error: unknown }).error === "object" &&
    (body as UnifiedEnvelopeShape).error !== null &&
    typeof (body as UnifiedEnvelopeShape).error.code === "string"
  );
}

/**
 * Parse a (possibly partial) API error body into a uniform shape.
 *
 * @param response  The fetch ``Response`` (used for HTTP status).
 * @param body      The decoded JSON body — pass through whatever
 *                  ``response.json()`` returned, even ``null`` or
 *                  ``undefined``. The adapter is forgiving.
 */
export function parseApiError(
  response: Pick<Response, "status" | "statusText">,
  body: unknown,
): ParsedApiError {
  if (isUnifiedEnvelope(body)) {
    const env = body.error;
    return {
      code: env.code,
      message: env.message,
      correlation_id: env.correlation_id ?? null,
      details: env.details ?? null,
      status: response.status,
    };
  }

  // Legacy ``{detail: ...}`` shape — pre-WP09.
  if (body && typeof body === "object" && "detail" in body) {
    const legacy = body as LegacyDetailShape;
    const detail = legacy.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail
          ? JSON.stringify(detail)
          : response.statusText || `HTTP ${response.status}`;
    // Surface any extra keys alongside ``detail`` (the old
    // ``next_allowed_at`` pattern) as ``details``.
    const { detail: _omit, ...rest } = legacy;
    return {
      code: "http_error",
      message,
      correlation_id: null,
      details: Object.keys(rest).length > 0 ? rest : null,
      status: response.status,
    };
  }

  // Last resort — body wasn't recognisable JSON; fall back on status text.
  return {
    code: "unknown",
    message: response.statusText || `HTTP ${response.status}`,
    correlation_id: null,
    details: body ?? null,
    status: response.status,
  };
}
