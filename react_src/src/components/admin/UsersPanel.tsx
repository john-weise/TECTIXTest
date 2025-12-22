// src/components/admin/UsersPanel.tsx
import React, { useEffect, useState } from "react";
import { User } from "../../types/admin";

/**
 * UsersPanel
 *
 * Admin operations:
 * - List users (GET /api/admin/users)
 * - Add user (POST /api/admin/users)
 * - Delete user (DELETE /api/admin/users/:username)
 * - Disable 2FA for a user (POST /api/admin/users/:username/2fa/disable)
 */
export default function UsersPanel() {
  const [users, setUsers] = useState<User[]>([]);
  const [newUser, setNewUser] = useState({
    username: "",
    password: "",
    is_admin: false,
  });
  const [loadingUser, setLoadingUser] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(false);

  const fetchUsers = async () => {
    try {
      setLoadingList(true);
      const res = await fetch("/api/admin/users", { credentials: "include" });
      if (!res.ok) {
        console.error("[UsersPanel] /api/admin/users returned", res.status);
        return;
      }
      const data = await res.json();
      setUsers(data);
    } catch (err) {
      console.error("[UsersPanel] Failed to fetch users", err);
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => {
    void fetchUsers();
  }, []);

  const addUser = async () => {
    if (!newUser.username.trim() || !newUser.password) {
      alert("Username & password required");
      return;
    }

    try {
      const payload = {
        username: newUser.username.trim(),
        password: newUser.password,
        is_admin: newUser.is_admin,
      };

      const res = await fetch("/api/admin/users", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        let msg = "Failed to add user";
        try {
          const data = await res.json();
          if (data.error) msg = data.error;
        } catch {
          // ignore
        }
        throw new Error(msg);
      }

      setNewUser({ username: "", password: "", is_admin: false });
      void fetchUsers();
    } catch (err: any) {
      console.error("[UsersPanel] Failed to add user", err);
      alert(err?.message || "Failed to add user");
    }
  };

  const deleteUser = async (username: string) => {
    if (!window.confirm(`Delete user ${username}?`)) return;

    try {
      setLoadingUser(username);
      const res = await fetch(
        `/api/admin/users/${encodeURIComponent(username)}`,
        {
          method: "DELETE",
          credentials: "include",
        }
      );

      if (!res.ok) {
        let msg = `Failed to delete user ${username}`;
        try {
          const data = await res.json();
          if (data.error) msg = data.error;
        } catch {
          // ignore
        }
        throw new Error(msg);
      }

      setUsers((prev) => prev.filter((u) => u.username !== username));
    } catch (err: any) {
      console.error("[UsersPanel] Failed to delete user", err);
      alert(err?.message || "Failed to delete user");
    } finally {
      setLoadingUser(null);
    }
  };

  const disableUser2FA = async (username: string) => {
    if (
      !window.confirm(
        `Disable 2FA for user ${username}? They will no longer be prompted for a second factor when logging in.`
      )
    ) {
      return;
    }

    try {
      setLoadingUser(username);
      const res = await fetch(
        `/api/admin/users/${encodeURIComponent(username)}/2fa/disable`,
        {
          method: "POST",
          credentials: "include",
        }
      );

      if (!res.ok) {
        let msg = `Failed to disable 2FA for ${username}`;
        try {
          const data = await res.json();
          if (data.error) msg = data.error;
        } catch {
          // ignore
        }
        throw new Error(msg);
      }

      // Refresh to update twofa_enabled flag
      await fetchUsers();
    } catch (err: any) {
      console.error("[UsersPanel] Failed to disable 2FA", err);
      alert(err?.message || "Failed to disable 2FA");
    } finally {
      setLoadingUser(null);
    }
  };

  return (
    <>
      <h2 className="section-title">User Management</h2>
      <div className="gold-rule" aria-hidden="true" />

      <h3 className="admin-subhead">Existing Users</h3>

      {loadingList && users.length === 0 && (
        <div className="user-empty">Loading users…</div>
      )}

      <ul className="user-list">
        {users.map((u) => {
          const is2faEnabled = !!u.twofa_enabled;
          const busy = loadingUser === u.username;

          return (
            <li className="user-row" key={u.username}>
              <div className="user-ident">
                <span className="user-name">{u.username}</span>
                {u.is_admin && <span className="user-badge">admin</span>}
                <span
                  className={`user-badge ${
                    is2faEnabled ? "user-badge--ok" : "user-badge--muted"
                  }`}
                >
                  2FA: {is2faEnabled ? "Enabled" : "Not enabled"}
                </span>
              </div>

              <div className="user-actions">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => disableUser2FA(u.username)}
                  disabled={!is2faEnabled || busy}
                  title={
                    is2faEnabled
                      ? "Disable 2FA for this user"
                      : "2FA is not enabled for this user"
                  }
                >
                  {busy && is2faEnabled ? "Disabling…" : "Disable 2FA"}
                </button>

                <button
                  type="button"
                  className="danger-button"
                  onClick={() => deleteUser(u.username)}
                  disabled={busy}
                >
                  Delete
                </button>
              </div>
            </li>
          );
        })}
        {!loadingList && users.length === 0 && (
          <li className="user-empty">No users found.</li>
        )}
      </ul>

      <h3 className="admin-subhead">Add New User</h3>
      <div className="admin-form">
        <input
          type="text"
          placeholder="Username"
          value={newUser.username}
          onChange={(e) =>
            setNewUser({ ...newUser, username: e.target.value })
          }
          className="admin-input"
        />
        <input
          type="password"
          placeholder="Password"
          value={newUser.password}
          onChange={(e) =>
            setNewUser({ ...newUser, password: e.target.value })
          }
          className="admin-input"
        />
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={newUser.is_admin}
            onChange={(e) =>
              setNewUser({ ...newUser, is_admin: e.target.checked })
            }
          />
          <span>Admin?</span>
        </label>
        <button className="generate-button" onClick={addUser}>
          Create User
        </button>
      </div>
    </>
  );
}

