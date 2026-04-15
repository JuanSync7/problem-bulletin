import React, { useState, useEffect, useCallback } from "react";
import { AdminRouteGuard } from "../../components/AdminRouteGuard";
import { useToast } from "../../contexts/ToastContext";
import "./Admin.css";

interface Tag {
  id: string;
  name: string;
  usageCount: number;
}

function TagsContent() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [mergeSourceId, setMergeSourceId] = useState<string | null>(null);
  const [mergeTargetId, setMergeTargetId] = useState("");
  const toast = useToast();

  const fetchTags = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/tags", { credentials: "include" });
      if (!res.ok) throw new Error("Failed to fetch tags");
      const data: Tag[] = await res.json();
      setTags(data);
    } catch {
      toast.show("Failed to load tags", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchTags();
  }, [fetchTags]);

  const filteredTags = tags.filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase()),
  );

  async function handleRename(id: string) {
    const trimmed = editName.trim();
    if (!trimmed) return;

    try {
      const res = await fetch(`/api/admin/tags/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: trimmed }),
      });
      if (!res.ok) throw new Error("Failed to rename tag");
      setEditingId(null);
      toast.show("Tag renamed", "success");
      await fetchTags();
    } catch {
      toast.show("Failed to rename tag", "error");
    }
  }

  async function handleDelete(id: string) {
    try {
      const res = await fetch(`/api/admin/tags/${id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to delete tag");
      setConfirmDeleteId(null);
      toast.show("Tag deleted", "success");
      await fetchTags();
    } catch {
      toast.show("Failed to delete tag", "error");
    }
  }

  async function handleMerge() {
    if (!mergeSourceId || !mergeTargetId) return;

    try {
      const res = await fetch("/api/admin/tags/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          sourceId: mergeSourceId,
          targetId: mergeTargetId,
        }),
      });
      if (!res.ok) throw new Error("Failed to merge tags");
      setMergeSourceId(null);
      setMergeTargetId("");
      toast.show("Tags merged", "success");
      await fetchTags();
    } catch {
      toast.show("Failed to merge tags", "error");
    }
  }

  function startEdit(tag: Tag) {
    setEditingId(tag.id);
    setEditName(tag.name);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditName("");
  }

  if (loading) {
    return (
      <div className="admin-page">
        <h1 className="admin-page__title">Tags</h1>
        <div className="admin-loading">
          <div className="admin-loading__spinner" />
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <h1 className="admin-page__title">Tags</h1>

      <div className="admin-toolbar">
        <input
          type="text"
          className="admin-input"
          placeholder="Search tags..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Merge Modal */}
      {mergeSourceId && (
        <div className="admin-modal-backdrop" onClick={() => setMergeSourceId(null)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="admin-modal__title">Merge Tag</h2>
            <p className="admin-modal__text">
              Merge &ldquo;{tags.find((t) => t.id === mergeSourceId)?.name}&rdquo; into:
            </p>
            <select
              className="admin-select"
              value={mergeTargetId}
              onChange={(e) => setMergeTargetId(e.target.value)}
            >
              <option value="">Select target tag...</option>
              {tags
                .filter((t) => t.id !== mergeSourceId)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.usageCount})
                  </option>
                ))}
            </select>
            <div className="admin-modal__actions">
              <button
                className="admin-btn admin-btn--primary"
                disabled={!mergeTargetId}
                onClick={handleMerge}
              >
                Merge
              </button>
              <button
                className="admin-btn"
                onClick={() => setMergeSourceId(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Tag Name</th>
              <th>Usage Count</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredTags.map((tag) => (
              <tr key={tag.id}>
                <td>
                  {editingId === tag.id ? (
                    <input
                      type="text"
                      className="admin-input admin-input--inline"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRename(tag.id);
                        if (e.key === "Escape") cancelEdit();
                      }}
                      autoFocus
                    />
                  ) : (
                    <span
                      className="admin-editable-text"
                      onClick={() => startEdit(tag)}
                      title="Click to rename"
                    >
                      {tag.name}
                    </span>
                  )}
                </td>
                <td>{tag.usageCount}</td>
                <td className="admin-table__actions-cell">
                  {editingId === tag.id ? (
                    <>
                      <button
                        className="admin-btn admin-btn--primary"
                        onClick={() => handleRename(tag.id)}
                      >
                        Save
                      </button>
                      <button className="admin-btn" onClick={cancelEdit}>
                        Cancel
                      </button>
                    </>
                  ) : confirmDeleteId === tag.id ? (
                    <>
                      <span className="admin-confirm-text">Delete?</span>
                      <button
                        className="admin-btn admin-btn--danger"
                        onClick={() => handleDelete(tag.id)}
                      >
                        Yes
                      </button>
                      <button
                        className="admin-btn"
                        onClick={() => setConfirmDeleteId(null)}
                      >
                        No
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="admin-btn"
                        onClick={() => startEdit(tag)}
                      >
                        Rename
                      </button>
                      <button
                        className="admin-btn"
                        onClick={() => setMergeSourceId(tag.id)}
                      >
                        Merge
                      </button>
                      <button
                        className="admin-btn admin-btn--danger"
                        onClick={() => setConfirmDeleteId(tag.id)}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {filteredTags.length === 0 && (
              <tr>
                <td colSpan={3} className="admin-table__empty">
                  {search ? "No tags match your search." : "No tags found."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Tags() {
  return (
    <AdminRouteGuard>
      <TagsContent />
    </AdminRouteGuard>
  );
}
