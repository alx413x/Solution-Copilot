"use client";
import { useState } from "react";
import { api } from "../../lib/client";
export default function Login() {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <main className="login">
      <p className="brand">Solution Copilot</p>
      <section>
        <p className="eyebrow">欢迎回来</p>
        <h1>进入工作台</h1>
        <p className="muted">
          使用管理员提供的访问凭据登录。仅可访问已授权的组织与客户。
        </p>
        <form
          className="record-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api("/api/session", "POST", { token });
              window.location.assign("/customers");
            } catch (e) {
              setError(e instanceof Error ? e.message : "登录失败");
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            访问凭据
            <input
              type="password"
              autoComplete="off"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" disabled={busy}>
            {busy ? "验证中…" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
