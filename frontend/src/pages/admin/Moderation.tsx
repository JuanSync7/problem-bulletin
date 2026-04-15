import React, { useState, useEffect, useCallback } from "react";
import { AdminRouteGuard } from "../../components/AdminRouteGuard";
import { useToast } from "../../contexts/ToastContext";
import "./Admin.css";

interface FlaggedItem {
  id: string;
  contentType: string;
  preview: string;
  flagCount: number;
  reporters: string[];
  createdAt: string;
}

function ModerationContent() {
  const [items, setItems] = useState<FlaggedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmDeAnon, setConfirmDeAnon] = useState<string | null>(null);
  const toast = useToast();

  const fetchFlags = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/moderation/flags", {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to fetch flagged items");
      const data: FlaggedItem[] = await res.json();
      setItems(data);
    } catch {
      toast.show("Failed to load flagged items", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchFlags();
  }, [fetchFlags]);

  async function handleResolve(id: string) {
    try {
      const res = await fetch(`/api/admin/moderation/flags/${id}/resolve`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to resolve flag");
      toast.show("Flag resolved", "success");
      await fetchFlags();
    } catch {
      toast.show("Failed to resolve flag", "error");
    }
  }

  async function handleDeAnonymize(id: string) {
    try {
      const res = await fetch(`/api/admin/moderation/de-anonymize/${id}`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to de-anonymize");
      setConfirmDeAnon(null);
      toast.show("Content de-anonymized", "success");
      await fetchFlags();
    } catch {
      toast.show("Failed to de-anonymize content", "error");
    }
  }

  if (loading) {
    return (
      <div className="admin-page">
        <h1 className="admin-page__title">Moderation</h1>
        <div className="admin-loading">
          <div className="admin-loading__spinner" />
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <h1 className="admin-page__title">Moderation</h1>

      {/* De-anonymize confirmation dialog */}
      {confirmDeAnon && (
        <div className="admin-modal-backdrop" onClick={() => setConfirmDeAnon(null)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="admin-modal__title">Confirm De-anonymize</h2>
            <p className="admin-modal__text">
              This will reveal the identity of the anonymous author. This action
              cannot be undone. Are you sure?
            </p>
            <div className="admin-modal__actions">
              <button
                className="admin-btn admin-btn--danger"
                onClick={() => handleDeAnonymize(confirmDeAnon)}
              >
                De-anonymize
              </button>
              <button
                className="admin-btn"
                onClick={() => setConfirmDeAnon(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div className="admin-empty-state">
          No flagged content to review.
        </div>
      ) : (
        <div className="admin-moderation-list">
          {items.map((item) => (
            <div key={item.id} className="admin-moderation-card">
              <div className="admin-moderation-card__header">
                <span className="admin-moderation-card__type">{item.contentType}</span>
                <span className="admin-moderation-card__flags">
                  {item.flagCount} {item.flagCount === 1 ? "flag" : "flags"}
                </span>
              </div>
              <p className="admin-moderation-card__preview">{item.preview}</p>
              <div className="admin-moderation-card__reporters">
                <span className="admin-moderation-card__reporters-label">
                  Reported by:
                </span>
                {item.reporters.map((r, i) => (
                  <span key={i} className="admin-moderation-card__reporter">
                    {r}
                  </span>
                ))}
              </div>
              <div className="admin-moderation-card__actions">
                <button
                  className="admin-btn admin-btn--primary"
                  onClick={() => handleResolve(item.id)}
                >
                  Resolve
                </button>
                <button
                  className="admin-btn admin-btn--danger"
                  onClick={() => setConfirmDeAnon(item.id)}
                >
                  De-anonymize
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Moderation() {
  return (
    <AdminRouteGuard>
      <ModerationContent />
    </AdminRouteGuard>
  );
}
