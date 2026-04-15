import React, { useState, useEffect, useCallback } from "react";
import { AdminRouteGuard } from "../../components/AdminRouteGuard";
import { useToast } from "../../contexts/ToastContext";
import "./Admin.css";

interface Category {
  id: string;
  name: string;
  sortOrder: number;
}

function CategoriesContent() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const toast = useToast();

  const fetchCategories = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/categories", { credentials: "include" });
      if (!res.ok) throw new Error("Failed to fetch categories");
      const data: Category[] = await res.json();
      setCategories(data);
    } catch {
      toast.show("Failed to load categories", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = newName.trim();
    if (!trimmed) return;

    try {
      const res = await fetch("/api/admin/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: trimmed }),
      });
      if (!res.ok) throw new Error("Failed to create category");
      setNewName("");
      toast.show("Category created", "success");
      await fetchCategories();
    } catch {
      toast.show("Failed to create category", "error");
    }
  }

  async function handleSaveEdit(id: string) {
    const trimmed = editName.trim();
    if (!trimmed) return;

    try {
      const res = await fetch(`/api/admin/categories/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: trimmed }),
      });
      if (!res.ok) throw new Error("Failed to update category");
      setEditingId(null);
      toast.show("Category updated", "success");
      await fetchCategories();
    } catch {
      toast.show("Failed to update category", "error");
    }
  }

  async function handleDelete(id: string) {
    try {
      const res = await fetch(`/api/admin/categories/${id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to delete category");
      setConfirmDeleteId(null);
      toast.show("Category deleted", "success");
      await fetchCategories();
    } catch {
      toast.show("Failed to delete category", "error");
    }
  }

  async function handleReorder(id: string, direction: "up" | "down") {
    try {
      const res = await fetch(`/api/admin/categories/${id}/reorder`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ direction }),
      });
      if (!res.ok) throw new Error("Failed to reorder");
      await fetchCategories();
    } catch {
      toast.show("Failed to reorder category", "error");
    }
  }

  function startEdit(cat: Category) {
    setEditingId(cat.id);
    setEditName(cat.name);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditName("");
  }

  if (loading) {
    return (
      <div className="admin-page">
        <h1 className="admin-page__title">Categories</h1>
        <div className="admin-loading">
          <div className="admin-loading__spinner" />
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <h1 className="admin-page__title">Categories</h1>

      <form className="admin-inline-form" onSubmit={handleCreate}>
        <input
          type="text"
          className="admin-input"
          placeholder="New category name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button type="submit" className="admin-btn admin-btn--primary">
          Create
        </button>
      </form>

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Order</th>
              <th>Name</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((cat, idx) => (
              <tr key={cat.id}>
                <td className="admin-table__order-cell">
                  <button
                    className="admin-btn admin-btn--icon"
                    disabled={idx === 0}
                    onClick={() => handleReorder(cat.id, "up")}
                    aria-label="Move up"
                  >
                    &#9650;
                  </button>
                  <button
                    className="admin-btn admin-btn--icon"
                    disabled={idx === categories.length - 1}
                    onClick={() => handleReorder(cat.id, "down")}
                    aria-label="Move down"
                  >
                    &#9660;
                  </button>
                </td>
                <td>
                  {editingId === cat.id ? (
                    <input
                      type="text"
                      className="admin-input admin-input--inline"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleSaveEdit(cat.id);
                        if (e.key === "Escape") cancelEdit();
                      }}
                      autoFocus
                    />
                  ) : (
                    <span
                      className="admin-editable-text"
                      onClick={() => startEdit(cat)}
                      title="Click to edit"
                    >
                      {cat.name}
                    </span>
                  )}
                </td>
                <td className="admin-table__actions-cell">
                  {editingId === cat.id ? (
                    <>
                      <button
                        className="admin-btn admin-btn--primary"
                        onClick={() => handleSaveEdit(cat.id)}
                      >
                        Save
                      </button>
                      <button className="admin-btn" onClick={cancelEdit}>
                        Cancel
                      </button>
                    </>
                  ) : confirmDeleteId === cat.id ? (
                    <>
                      <span className="admin-confirm-text">Delete?</span>
                      <button
                        className="admin-btn admin-btn--danger"
                        onClick={() => handleDelete(cat.id)}
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
                        onClick={() => startEdit(cat)}
                      >
                        Edit
                      </button>
                      <button
                        className="admin-btn admin-btn--danger"
                        onClick={() => setConfirmDeleteId(cat.id)}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {categories.length === 0 && (
              <tr>
                <td colSpan={3} className="admin-table__empty">
                  No categories yet. Create one above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Categories() {
  return (
    <AdminRouteGuard>
      <CategoriesContent />
    </AdminRouteGuard>
  );
}
