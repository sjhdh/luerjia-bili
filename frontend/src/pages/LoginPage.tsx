import { Activity, LoaderCircle, LockKeyhole, Radio, ShieldCheck } from "lucide-react";
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
      <section className="login-context">
        <div className="login-brand"><span><Activity size={22} /></span><div><strong>路尔嘉舆情分析</strong><small>SIGNAL DESK</small></div></div>
        <div className="login-statement"><p>PRIVATE OPERATIONS</p><h1>舆情信号<br />汇入一处</h1></div>
        <div className="login-signal-list">
          <span><i className="bili-swatch" /><b>BILIBILI</b><small>官号 / 相关视频</small></span>
          <span><i className="taptap-swatch" /><b>TAPTAP</b><small>玩家评价</small></span>
          <span><Radio size={15} /><b>LOCAL NLP</b><small>本地模型</small></span>
        </div>
      </section>
      <section className="login-panel">
        <div className="login-heading"><ShieldCheck size={22} /><div><p className="panel-kicker">OPERATOR ACCESS</p><h2>登录工作台</h2><span>仅限内部操作者访问</span></div></div>
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
