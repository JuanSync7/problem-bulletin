import React, { useState, useEffect, useRef, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useDarkMode } from "../hooks/useDarkMode";
import { useToast } from "../contexts/ToastContext";
import { useAuth } from "../hooks/useAuth";
import { updateMyHandle } from "../api/users";
import type { UpdateHandleError } from "../api/users";
import {
  listAuditLog,
  type AuditLogEntry,
  type ListAuditLogParams,
} from "../api/auditLog";
import { PersonPicker } from "../components/PersonPicker/index";
import type { PersonRef } from "../api/people";
import { parseApiError } from "../api/errors";
import "./Settings.css";

// Client-side handle validation (mirrors backend rules).
const HANDLE_RE = /^[a-z0-9_]+$/;

function validateHandle(value: string): string | null {
  if (value.length < 3 || value.length > 32) {
    return "Handle must be 3–32 characters.";
  }
  if (!HANDLE_RE.test(value)) {
    return "Only lowercase letters, digits, and underscores are allowed.";
  }
  if (value[0] === "_") {
    return "Handle must not start with an underscore.";
  }
  if (value[0] >= "0" && value[0] <= "9") {
    return "Handle must not start with a digit.";
  }
  return null;
}

function formatDatetime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function relativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hrs = Math.floor(min / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  } catch {
    return iso;
  }
}

function truncateJson(obj: Record<string, unknown>, maxLen = 80): string {
  const s = JSON.stringify(obj);
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 1) + "…";
}

interface NotificationPrefs {
  emailOnComments: boolean;
  emailOnSolutions: boolean;
  emailOnStatusChanges: boolean;
}

// ---------------------------------------------------------------------------
// Admin section — Audit-log table
// ---------------------------------------------------------------------------

function AuditLogTable() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [eventFilter, setEventFilter] = useState("");
  const [actorFilter, setActorFilter] = useState<PersonRef | null>(null);

  // Expanded metadata rows
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const fetchPage = useCallback(
    async (
      params: ListAuditLogParams,
      replace: boolean
    ) => {
      setLoading(true);
      setError(null);
      try {
        const page = await listAuditLog(params);
        const items = page.items ?? [];
        setEntries((prev) => (replace ? items : [...prev, ...items]));
        setNextCursor(page.next_cursor ?? null);
        if (replace) setTotal(page.total ?? null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load audit log");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  // Initial load + filter-change reload
  useEffect(() => {
    fetchPage(
      {
        limit: 50,
        event: eventFilter || null,
        actor_user_id: actorFilter?.id ?? null,
      },
      true
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventFilter, actorFilter]);

  function handleLoadMore() {
    if (!nextCursor) return;
    fetchPage(
      {
        cursor: nextCursor,
        limit: 50,
        event: eventFilter || null,
        actor_user_id: actorFilter?.id ?? null,
      },
      false
    );
  }

  function toggleExpand(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="settings__audit">
      {/* Filter bar */}
      <div className="settings__audit-filters">
        <input
          type="text"
          className="settings__audit-filter-input"
          placeholder="Filter by event (exact)"
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
          aria-label="Filter by event"
        />
        <div className="settings__audit-actor-picker">
          <PersonPicker
            value={actorFilter}
            onChange={setActorFilter}
            kind="user"
            placeholder="Filter by actor"
            allowClear
          />
        </div>
        {/* v2.6-WP44: quick-filter chip for the handle-override event. */}
        <button
          type="button"
          className={`settings__audit-quick-filter${
            eventFilter === "user.handle_changed_by_admin"
              ? " settings__audit-quick-filter--active"
              : ""
          }`}
          aria-pressed={eventFilter === "user.handle_changed_by_admin"}
          onClick={() =>
            setEventFilter((prev) =>
              prev === "user.handle_changed_by_admin"
                ? ""
                : "user.handle_changed_by_admin"
            )
          }
        >
          Handle overrides
        </button>
      </div>

      {/* Summary */}
      {total != null && (
        <p className="settings__audit-total">{total} total entries</p>
      )}

      {error && <p className="settings__field-message--error">{error}</p>}

      {/* Table */}
      <div className="settings__audit-table-wrap">
        <table className="settings__audit-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Actor</th>
              <th>Target</th>
              <th>Metadata</th>
            </tr>
          </thead>
          <tbody>
            {(entries ?? []).map((entry) => {
              const isExpanded = expandedIds.has(entry.id);
              const metaStr = JSON.stringify(entry.metadata, null, 2);
              const metaPreview = truncateJson(entry.metadata);
              const hasMore = metaStr.length > 80;

              return (
                <tr key={entry.id}>
                  <td
                    className="settings__audit-cell settings__audit-cell--time"
                    title={formatDatetime(entry.created_at)}
                  >
                    {relativeTime(entry.created_at)}
                  </td>
                  <td className="settings__audit-cell settings__audit-cell--event">
                    {entry.event}
                  </td>
                  <td className="settings__audit-cell">
                    {entry.actor
                      ? `@${entry.actor.handle ?? entry.actor.display_name}`
                      : entry.actor_user_id
                      ? entry.actor_user_id.slice(0, 8)
                      : "—"}
                  </td>
                  <td className="settings__audit-cell">
                    {entry.target_type
                      ? `${entry.target_type}#${(entry.target_id ?? "").slice(0, 8)}`
                      : "—"}
                  </td>
                  <td className="settings__audit-cell settings__audit-cell--meta">
                    {isExpanded ? (
                      <>
                        <pre className="settings__audit-meta-pre">{metaStr}</pre>
                        {hasMore && (
                          <button
                            className="settings__audit-expand-btn"
                            onClick={() => toggleExpand(entry.id)}
                          >
                            collapse
                          </button>
                        )}
                      </>
                    ) : (
                      <>
                        <code>{metaPreview}</code>
                        {hasMore && (
                          <button
                            className="settings__audit-expand-btn"
                            onClick={() => toggleExpand(entry.id)}
                          >
                            expand
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
            {(entries ?? []).length === 0 && !loading && (
              <tr>
                <td colSpan={5} className="settings__audit-empty">
                  No audit entries found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {nextCursor && (
        <div className="settings__audit-load-more">
          <button
            className="settings__save-btn"
            onClick={handleLoadMore}
            disabled={loading}
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
      {loading && entries.length === 0 && (
        <p className="settings__audit-loading">Loading…</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Settings component
// ---------------------------------------------------------------------------

type Section = "profile" | "admin";

export default function Settings() {
  const { isDark, toggle } = useDarkMode();
  const { show } = useToast();
  const { user, fetchMe } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const isAdmin = (user as { role?: string })?.role === "admin";

  // Section routing
  const rawSection = searchParams.get("section") as Section | null;
  const section: Section =
    rawSection === "admin" && isAdmin ? "admin" : "profile";

  function switchSection(s: Section) {
    setSearchParams(s === "profile" ? {} : { section: s });
  }

  // --- Handle section state ---
  const [handleInput, setHandleInput] = useState<string>("");
  const [handleError, setHandleError] = useState<string | null>(null);
  const [handleSuccess, setHandleSuccess] = useState<string | null>(null);
  const [handleSaving, setHandleSaving] = useState(false);
  const [cooldownUntil, setCooldownUntil] = useState<string | null>(null);
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Initialise input from current user once available.
  useEffect(() => {
    if (user && !handleInput) {
      setHandleInput((user as unknown as { handle?: string }).handle ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // Clear cooldown lock if the countdown has passed.
  useEffect(() => {
    if (!cooldownUntil) return;
    const msLeft = new Date(cooldownUntil).getTime() - Date.now();
    if (msLeft <= 0) {
      setCooldownUntil(null);
      return;
    }
    const t = setTimeout(() => setCooldownUntil(null), msLeft);
    return () => clearTimeout(t);
  }, [cooldownUntil]);

  function handleHandleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value.toLowerCase();
    setHandleInput(raw);
    setHandleError(null);
    setHandleSuccess(null);
  }

  async function handleSaveHandle(e: React.FormEvent) {
    e.preventDefault();
    const clientError = validateHandle(handleInput);
    if (clientError) {
      setHandleError(clientError);
      return;
    }
    setHandleSaving(true);
    setHandleError(null);
    setHandleSuccess(null);
    try {
      await updateMyHandle(handleInput);
      setHandleSuccess("Handle updated.");
      await fetchMe();
      if (successTimerRef.current) clearTimeout(successTimerRef.current);
      successTimerRef.current = setTimeout(() => setHandleSuccess(null), 4000);
    } catch (err) {
      const apiErr = err as UpdateHandleError;
      if (apiErr.status === 409) {
        setHandleError("That handle is already taken.");
      } else if (apiErr.status === 429 && apiErr.next_allowed_at) {
        setCooldownUntil(apiErr.next_allowed_at);
        setHandleError(
          `You can change your handle again at ${formatDatetime(apiErr.next_allowed_at)}.`
        );
      } else {
        setHandleError(apiErr.detail || "Failed to update handle.");
      }
    } finally {
      setHandleSaving(false);
    }
  }

  // --- Notification prefs section state (existing) ---
  const [prefs, setPrefs] = useState<NotificationPrefs>({
    emailOnComments: true,
    emailOnSolutions: true,
    emailOnStatusChanges: true,
  });
  const [isSaving, setIsSaving] = useState(false);

  function handleToggle(key: keyof NotificationPrefs) {
    setPrefs((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleSaveNotifications() {
    setIsSaving(true);
    try {
      const res = await fetch("/api/auth/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          notifications: prefs,
          theme: isDark ? "dark" : "light",
        }),
      });
      if (!res.ok) {
        // v2.14-WP04: surface backend envelope message via parseApiError.
        const body = await res.json().catch(() => null);
        const parsed = parseApiError(res, body);
        throw new Error(parsed.message);
      }
      show("Settings saved successfully", "success");
    } catch (err) {
      show(
        err instanceof Error ? err.message : "Failed to save settings",
        "error"
      );
    } finally {
      setIsSaving(false);
    }
  }

  const currentHandle = (user as unknown as { handle?: string })?.handle ?? "";
  const handleUnchanged = handleInput === currentHandle;
  const handleClientError = handleInput ? validateHandle(handleInput) : null;
  const saveHandleDisabled =
    handleSaving ||
    !!cooldownUntil ||
    handleUnchanged ||
    !!handleClientError;

  return (
    <div className="settings">
      <h1 className="settings__title">Settings</h1>

      {/* Tab bar */}
      <div className="settings__tabs" role="tablist">
        <button
          role="tab"
          aria-selected={section === "profile"}
          className={`settings__tab${section === "profile" ? " settings__tab--active" : ""}`}
          onClick={() => switchSection("profile")}
        >
          Profile
        </button>
        {isAdmin && (
          <button
            role="tab"
            aria-selected={section === "admin"}
            className={`settings__tab${section === "admin" ? " settings__tab--active" : ""}`}
            onClick={() => switchSection("admin")}
          >
            Admin
          </button>
        )}
      </div>

      {/* ---- Profile section ---- */}
      {section === "profile" && (
        <>
          <div className="settings__section">
            <h2 className="settings__section-title">Profile</h2>

            <form onSubmit={handleSaveHandle} noValidate>
              <div className="settings__field-row">
                <label className="settings__field-label" htmlFor="handle-input">
                  Handle
                </label>
                <div className="settings__field-input-wrap">
                  <span className="settings__handle-prefix">@</span>
                  <input
                    id="handle-input"
                    type="text"
                    className={`settings__field-input${handleError ? " settings__field-input--error" : ""}`}
                    value={handleInput}
                    onChange={handleHandleChange}
                    minLength={3}
                    maxLength={32}
                    pattern="^[a-z0-9_]+$"
                    autoComplete="off"
                    spellCheck={false}
                    disabled={handleSaving}
                    aria-describedby={
                      handleError
                        ? "handle-error"
                        : handleSuccess
                        ? "handle-success"
                        : undefined
                    }
                  />
                </div>
              </div>

              {handleError && (
                <p id="handle-error" className="settings__field-message settings__field-message--error">
                  {handleError}
                </p>
              )}
              {handleSuccess && !handleError && (
                <p id="handle-success" className="settings__field-message settings__field-message--success">
                  {handleSuccess}
                </p>
              )}
              {!handleError && !handleSuccess && handleInput && handleClientError && (
                <p className="settings__field-message settings__field-message--error">
                  {handleClientError}
                </p>
              )}

              <div className="settings__field-actions">
                <button
                  type="submit"
                  className="settings__save-btn"
                  disabled={saveHandleDisabled}
                >
                  {handleSaving ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>

          {/* Notification Preferences section */}
          <div className="settings__section">
            <h2 className="settings__section-title">Notification Preferences</h2>

            <div className="settings__toggle-row">
              <div>
                <div className="settings__toggle-label">Comments</div>
                <div className="settings__toggle-description">
                  Email me when someone comments on my problems
                </div>
              </div>
              <label className="settings__switch">
                <input
                  type="checkbox"
                  checked={prefs.emailOnComments}
                  onChange={() => handleToggle("emailOnComments")}
                />
                <span className="settings__switch-track" />
              </label>
            </div>

            <div className="settings__toggle-row">
              <div>
                <div className="settings__toggle-label">Solutions</div>
                <div className="settings__toggle-description">
                  Email me when a solution is submitted to my problems
                </div>
              </div>
              <label className="settings__switch">
                <input
                  type="checkbox"
                  checked={prefs.emailOnSolutions}
                  onChange={() => handleToggle("emailOnSolutions")}
                />
                <span className="settings__switch-track" />
              </label>
            </div>

            <div className="settings__toggle-row">
              <div>
                <div className="settings__toggle-label">Status Changes</div>
                <div className="settings__toggle-description">
                  Email me when problem status changes
                </div>
              </div>
              <label className="settings__switch">
                <input
                  type="checkbox"
                  checked={prefs.emailOnStatusChanges}
                  onChange={() => handleToggle("emailOnStatusChanges")}
                />
                <span className="settings__switch-track" />
              </label>
            </div>
          </div>

          {/* Appearance section */}
          <div className="settings__section">
            <h2 className="settings__section-title">Appearance</h2>

            <div className="settings__toggle-row">
              <div>
                <div className="settings__toggle-label">Dark Mode</div>
                <div className="settings__toggle-description">
                  Toggle between light and dark theme
                </div>
              </div>
              <label className="settings__switch">
                <input
                  type="checkbox"
                  checked={isDark}
                  onChange={toggle}
                />
                <span className="settings__switch-track" />
              </label>
            </div>
          </div>

          <div className="settings__section settings__section--coming-soon">
            <h2 className="settings__section-title">Privacy</h2>
            <p className="settings__coming-soon">Coming soon</p>
          </div>

          <div className="settings__actions">
            <button
              className="settings__save-btn"
              onClick={handleSaveNotifications}
              disabled={isSaving}
              type="button"
            >
              {isSaving ? "Saving..." : "Save Settings"}
            </button>
          </div>
        </>
      )}

      {/* ---- Admin section ---- */}
      {section === "admin" && isAdmin && (
        <div className="settings__section settings__section--wide">
          <h2 className="settings__section-title">Audit Log</h2>
          <AuditLogTable />
        </div>
      )}
    </div>
  );
}
