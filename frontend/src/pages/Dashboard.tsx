import { useCallback, useEffect, useState } from "react";
import { Cable, LoaderCircle, LogOut, Play, RefreshCw, ScanSearch } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import BrowserWorkspace from "../components/BrowserWorkspace";
import StatusBadge from "../components/StatusBadge";
import type { BrowserSession, Job } from "../types";

type Platform = BrowserSession["platform"];

function emptySession(platform: Platform): BrowserSession {
  return {
    platform,
    running: false,
    authenticated: false,
    login_method: "window",
    qr_ready: false,
    qr_expires_at: null,
    message: "页面子窗口未连接",
    workspace_ready: false,
    current_url: null,
    page_title: null,
    risk_detected: false
  };
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [sessions, setSessions] = useState<Record<Platform, BrowserSession>>({
    bilibili: emptySession("bilibili"),
    taptap: emptySession("taptap")
  });
  const [workspace, setWorkspace] = useState<Platform | null>(null);
  const [keyword, setKeyword] = useState("");
  const [officialUrl, setOfficialUrl] = useState("");
  const [taptapUrl, setTapTapUrl] = useState("");
  const [includeDiscovery, setIncludeDiscovery] = useState(true);
  const [includeTapTap, setIncludeTapTap] = useState(true);
  const [timeRange, setTimeRange] = useState("90d");
  const [depth, setDepth] = useState("standard");
  const [analysisMode, setAnalysisMode] = useState("local");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [jobRows, bilibili, taptap] = await Promise.all([
      api.jobs(),
      api.platformSession("bilibili"),
      api.platformSession("taptap")
    ]);
    setJobs(jobRows);
    setSessions({ bilibili, taptap });
  }, []);

  useEffect(() => {
    void refresh().catch((err: Error) => setError(err.message));
    const timer = window.setInterval(() => void refresh().catch(() => undefined), 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function connect(platform: Platform) {
    setLoading(true);
    setError("");
    try {
      const next = await api.openWorkspace(platform);
      setSessions((current) => ({ ...current, [platform]: next }));
      setWorkspace(platform);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function disconnect(platform: Platform) {
    const label = platform === "bilibili" ? "B站" : "TapTap";
    if (!window.confirm(`清除服务器上的 ${label} 登录资料？`)) return;
    const next = await api.disconnectPlatform(platform);
    setSessions((current) => ({ ...current, [platform]: next }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const job = await api.createJob({
        keyword,
        official_bilibili_url: officialUrl || null,
        include_discovery: includeDiscovery,
        include_taptap: includeTapTap,
        taptap_app_url: taptapUrl || null,
        time_range: timeRange,
        depth,
        analysis_mode: analysisMode
      });
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="workspace">
      <section className="workspace-header">
        <div><p className="eyebrow">内部舆情工作台</p><h1>分析任务</h1></div>
        <div className="platform-connections">
          {(["bilibili", "taptap"] as Platform[]).map((platform) => {
            const session = sessions[platform];
            const label = platform === "bilibili" ? "B站" : "TapTap";
            return <div className={`connection ${session.authenticated ? "connected" : ""}`} key={platform}>
              <span className={`connection-dot source-${platform}`} />
              <div><strong>{label}{session.authenticated ? "已连接" : "未连接"}</strong><small>{session.message}</small></div>
              <button className="icon-button" title={`打开 ${label} 页面子窗口`} onClick={() => void connect(platform)}><Cable size={17} /></button>
              {session.running && <button className="icon-button danger" title={`清除 ${label} 登录资料`} onClick={() => void disconnect(platform)}><LogOut size={17} /></button>}
            </div>;
          })}
        </div>
      </section>

      {error && <div className="alert error-alert">{error}</div>}

      <section className="task-composer">
        <div className="section-heading"><h2>新建分析</h2><span>官号、相关视频与 TapTap 分区汇总</span></div>
        <form onSubmit={submit} className="task-form expanded-task-form">
          <label className="field keyword-field"><span>关键词</span><input value={keyword} onChange={(event) => setKeyword(event.target.value)} minLength={2} maxLength={64} required placeholder="游戏、产品或事件名称" /></label>
          <label className="field source-url-field"><span>B站官号地址</span><input value={officialUrl} onChange={(event) => setOfficialUrl(event.target.value)} placeholder="https://space.bilibili.com/3546785396034301" /></label>
          <label className="field source-url-field"><span>TapTap 应用地址</span><input value={taptapUrl} onChange={(event) => setTapTapUrl(event.target.value)} placeholder="https://www.taptap.cn/app/123456" /></label>
          <div className="source-toggles">
            <label><input type="checkbox" checked={includeDiscovery} onChange={(event) => setIncludeDiscovery(event.target.checked)} /><span>B站相关视频</span></label>
            <label><input type="checkbox" checked={includeTapTap} onChange={(event) => setIncludeTapTap(event.target.checked)} /><span>TapTap 评价</span></label>
          </div>
          <label className="field"><span>时间范围</span><select value={timeRange} onChange={(event) => setTimeRange(event.target.value)}><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="180d">近 180 天</option><option value="all">全部</option></select></label>
          <label className="field"><span>采集深度</span><select value={depth} onChange={(event) => setDepth(event.target.value)}><option value="light">轻量</option><option value="standard">标准</option><option value="deep">深度</option></select></label>
          <fieldset className="field mode-field"><legend>分析模式</legend><div className="segmented"><button type="button" className={analysisMode === "local" ? "active" : ""} onClick={() => setAnalysisMode("local")}>本地</button><button type="button" className={analysisMode === "enhanced" ? "active" : ""} onClick={() => setAnalysisMode("enhanced")}>LLM 增强</button></div></fieldset>
          <button className="button primary start-button" disabled={loading || keyword.trim().length < 2 || (!officialUrl && !includeDiscovery && !includeTapTap)}>{loading ? <LoaderCircle className="spin" size={18} /> : <ScanSearch size={18} />}开始分析</button>
        </form>
      </section>

      <section className="task-history">
        <div className="section-heading"><h2>历史任务</h2><button className="icon-button" title="刷新任务" onClick={() => void refresh()}><RefreshCw size={17} /></button></div>
        {jobs.length === 0 ? <div className="empty-state">暂无任务</div> : (
          <div className="table-wrap"><table><thead><tr><th>关键词</th><th>来源</th><th>状态</th><th>进度</th><th>创建时间</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{jobs.map((job) => (
            <tr key={job.id} onClick={() => navigate(`/jobs/${job.id}`)}><td><strong>{job.keyword}</strong><small>{job.stage}</small></td><td><span className="source-summary">{job.official_mid ? "官号 " : ""}{job.include_discovery ? "相关视频 " : ""}{job.include_taptap ? "TapTap" : ""}</span></td><td><StatusBadge status={job.status} /></td><td><div className="mini-progress"><span style={{ width: `${job.progress}%` }} /></div><small>{job.progress}%</small></td><td>{new Date(job.created_at).toLocaleString("zh-CN")}</td><td><button className="icon-button" title="打开任务"><Play size={16} /></button></td></tr>
          ))}</tbody></table></div>
        )}
      </section>

      <BrowserWorkspace
        platform={workspace || "bilibili"}
        open={workspace !== null}
        onClose={() => setWorkspace(null)}
        onSession={(next) => setSessions((current) => ({ ...current, [next.platform]: next }))}
      />
    </div>
  );
}
