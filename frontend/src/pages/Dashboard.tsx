import { useCallback, useEffect, useState } from "react";
import { Cable, LoaderCircle, LogOut, Play, QrCode, RefreshCw, Server } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import StatusBadge from "../components/StatusBadge";
import type { BrowserSession, Job } from "../types";

const initialSession: BrowserSession = {
  running: false,
  authenticated: false,
  login_method: "window",
  qr_ready: false,
  qr_expires_at: null,
  message: "浏览器未连接"
};

export default function Dashboard() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [session, setSession] = useState(initialSession);
  const [keyword, setKeyword] = useState("");
  const [timeRange, setTimeRange] = useState("90d");
  const [depth, setDepth] = useState("standard");
  const [analysisMode, setAnalysisMode] = useState("local");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [qrVersion, setQrVersion] = useState(0);
  const [clock, setClock] = useState(Date.now());

  const refresh = useCallback(async () => {
    const [jobRows, sessionState] = await Promise.all([api.jobs(), api.session()]);
    setJobs(jobRows);
    setSession(sessionState);
  }, []);

  useEffect(() => {
    void refresh().catch((err: Error) => setError(err.message));
    const timer = window.setInterval(() => void refresh().catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  async function connect() {
    setLoading(true);
    setError("");
    try {
      const next = await api.connect(session.login_method);
      setSession(next);
      setQrVersion(Date.now());
      setClock(Date.now());
    } catch (err) { setError((err as Error).message); }
    finally { setLoading(false); }
  }

  async function disconnect() {
    const location = session.login_method === "qr" ? "服务器" : "本机";
    if (!window.confirm(`清除${location}上的 B站登录资料？`)) return;
    setSession(await api.disconnect());
  }

  const secondsRemaining = session.qr_expires_at
    ? Math.max(0, Math.ceil((new Date(session.qr_expires_at).getTime() - clock) / 1000))
    : 0;
  const qrPanelVisible = session.login_method === "qr" && !session.authenticated && Boolean(session.qr_expires_at);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const job = await api.createJob({ keyword, time_range: timeRange, depth, analysis_mode: analysisMode });
      navigate(`/jobs/${job.id}`);
    } catch (err) { setError((err as Error).message); }
    finally { setLoading(false); }
  }

  return (
    <div className="workspace">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">{session.login_method === "qr" ? "服务器私有工作台" : "本机工作台"}</p>
          <h1>舆情任务</h1>
        </div>
        <div className={`connection ${session.authenticated ? "connected" : ""}`}>
          <span className="connection-dot" />
          <div><strong>{session.authenticated ? "B站已连接" : "B站未连接"}</strong><small>{session.message}</small></div>
          <button className="icon-button" title="刷新状态" onClick={() => void refresh()}><RefreshCw size={17} /></button>
          {session.authenticated ?
            <button className="icon-button danger" title="断开并清除登录资料" onClick={() => void disconnect()}><LogOut size={17} /></button> :
            <button className="button secondary" onClick={() => void connect()} disabled={loading}>{session.login_method === "qr" ? <QrCode size={17} /> : <Cable size={17} />}{session.login_method === "qr" ? (session.qr_ready ? "刷新二维码" : "生成二维码") : "连接 B站"}</button>}
        </div>
      </section>

      {error && <div className="alert error-alert">{error}</div>}

      {qrPanelVisible && (
        <section className="qr-login-panel" aria-live="polite">
          <div className={`qr-image-wrap ${session.qr_ready && secondsRemaining > 0 ? "" : "expired"}`}>
            {session.qr_ready && secondsRemaining > 0
              ? <img src={`/api/v1/bilibili/qr-code.png?v=${qrVersion}`} alt="B站登录二维码" />
              : <QrCode size={54} />}
          </div>
          <div className="qr-login-copy">
            <p className="eyebrow"><Server size={14} />服务器扫码登录</p>
            <h2>{secondsRemaining > 0 ? "使用哔哩哔哩客户端扫码" : "二维码已过期"}</h2>
            <p>{secondsRemaining > 0 ? "扫码后在手机端确认，页面会自动更新连接状态。" : "重新生成二维码后即可继续，不需要向服务器提交账号密码。"}</p>
            <div className="qr-login-actions">
              <span>{secondsRemaining > 0 ? `${secondsRemaining} 秒后过期` : "等待刷新"}</span>
              <button className="button secondary" onClick={() => void connect()} disabled={loading}><RefreshCw size={16} />重新生成</button>
            </div>
          </div>
        </section>
      )}

      <section className="task-composer">
        <div className="section-heading"><h2>新建分析</h2><span>评论、可见弹幕与 TapTap 评价</span></div>
        <form onSubmit={submit} className="task-form">
          <label className="field keyword-field"><span>关键词</span><input value={keyword} onChange={(e) => setKeyword(e.target.value)} minLength={2} maxLength={64} required placeholder="输入游戏、产品或事件名称" /></label>
          <label className="field"><span>时间范围</span><select value={timeRange} onChange={(e) => setTimeRange(e.target.value)}><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="180d">近 180 天</option><option value="all">全部</option></select></label>
          <label className="field"><span>采集深度</span><select value={depth} onChange={(e) => setDepth(e.target.value)}><option value="light">轻量 · 250 评论</option><option value="standard">标准 · 1000 评论</option><option value="deep">深度 · 3000 评论</option></select></label>
          <fieldset className="field mode-field"><legend>分析模式</legend><div className="segmented"><button type="button" className={analysisMode === "local" ? "active" : ""} onClick={() => setAnalysisMode("local")}>本地</button><button type="button" className={analysisMode === "enhanced" ? "active" : ""} onClick={() => setAnalysisMode("enhanced")}>LLM 增强</button></div></fieldset>
          <button className="button primary start-button" disabled={loading || keyword.trim().length < 2}>{loading ? <LoaderCircle className="spin" size={18} /> : <Play size={18} />}开始分析</button>
        </form>
      </section>

      <section className="task-history">
        <div className="section-heading"><h2>历史任务</h2><span>{jobs.length} 条</span></div>
        {jobs.length === 0 ? <div className="empty-state">暂无任务</div> : (
          <div className="table-wrap"><table><thead><tr><th>关键词</th><th>状态</th><th>进度</th><th>模式</th><th>创建时间</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{jobs.map((job) => (
            <tr key={job.id} onClick={() => navigate(`/jobs/${job.id}`)}><td><strong>{job.keyword}</strong><small>{job.stage}</small></td><td><StatusBadge status={job.status} /></td><td><div className="mini-progress"><span style={{ width: `${job.progress}%` }} /></div><small>{job.progress}%</small></td><td>{job.analysis_mode === "enhanced" ? "LLM 增强" : "本地"}</td><td>{new Date(job.created_at).toLocaleString("zh-CN")}</td><td><button className="icon-button" title="打开任务"><Play size={16} /></button></td></tr>
          ))}</tbody></table></div>
        )}
      </section>
    </div>
  );
}
