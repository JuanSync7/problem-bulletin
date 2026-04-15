import React, { useState, useEffect, useCallback } from "react";
import { AdminRouteGuard } from "../../components/AdminRouteGuard";
import { useToast } from "../../contexts/ToastContext";
import "./Admin.css";

interface AdminUser {
  id: string;
  displayName: string;
  email: string;
  role: string;
  status: string;
}

function UsersContent() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const toast = useToast();

  const fetchUsers = useCallback(async () => {
    try {
      const params = search ? `?q=${encodeURIComponent(search)}` : "";
      const res = await fetch(`/api/admin/users${params}`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to fetch users");
      const data: AdminUser[] = await res.json();
      setUsers(data);
    } catch {
      toast.show("Failed to load users", "error");
    } finally {
      setLoading(false);
    }
  }, [search, toast]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  async function handleRoleChange(userId: string, newRole: string) {
    try {
      const res = await fetch(`/api/admin/users/${userId}/role`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ role: newRole }),
      });
      if (!res.ok) throw new Error("Failed to update role");
      toast.show("User role updated", "success");
      await fetchUsers();
    } catch {
      toast.show("Failed to update role", "error");
    }
  }

  async function handleStatusToggle(userId: string, currentStatus: string) {
    const newStatus = currentStatus === "active" ? "inactive" : "active";
    try {
      const res = await fetch(`/api/admin/users/${userId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status: newStatus }),
      });
      if (!res.ok) throw new Error("Failed to update status");
      toast.show(`User ${newStatus === "active" ? "activated" : "deactivated"}`, "success");
      await fetchUsers();
    } catch {
      toast.show("Failed to update status", "error");
    }
  }

  return (
    <div className="admin-page">
      <h1 className="admin-page__title">Users</h1>

      <div className="admin-toolbar">
        <input
          type="text"
          className="admin-input"
          placeholder="Search by name or email..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <div className="admin-loading">
          <div className="admin-loading__spinner" />
        </div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.displayName}</td>
                  <td>{user.email}</td>
                  <td>
                    <select
                      className="admin-select admin-select--inline"
                      value={user.role}
                      onChange={(e) => handleRoleChange(user.id, e.target.value)}
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td>
                    <span
                      className={`admin-status-badge admin-status-badge--${user.status}`}
                    >
                      {user.status}
                    </span>
                  </td>
                  <td>
                    <button
                      className="admin-btn"
                      onClick={() => handleStatusToggle(user.id, user.status)}
                    >
                      {user.status === "active" ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="admin-table__empty">
                    {search ? "No users match your search." : "No users found."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function Users() {
  return (
    <AdminRouteGuard>
      <UsersContent />
    </AdminRouteGuard>
  );
}
