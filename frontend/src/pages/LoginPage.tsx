import { BarChart3, LoaderCircle, LockKeyhole } from "lucide-react";
import { useState } from "react";
import { api } from "../api";

export default function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(username, password);
      onSuccess();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="login-brand"><span><BarChart3 size={22} /></span><strong>路尔嘉舆情分析</strong></div>
        <div className="login-heading"><LockKeyhole size={22} /><div><h1>登录工作台</h1><p>仅限内部操作者访问</p></div></div>
        {error && <div className="alert error-alert">{error}</div>}
        <form onSubmit={submit} className="login-form">
          <label className="field"><span>账号</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
          <label className="field"><span>密码</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required autoFocus /></label>
          <button className="button primary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={18} /> : <LockKeyhole size={17} />}登录</button>
        </form>
      </section>
    </main>
  );
}
