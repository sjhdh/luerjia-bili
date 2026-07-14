import { useCallback, useEffect, useState } from "react";
import { Cable, ChevronRight, LoaderCircle, LogOut, MessageSquareText, Play, Radio, RefreshCw, Route, ScanSearch } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import BrowserWorkspace from "../components/BrowserWorkspace";
import StatusBadge from "../components/StatusBadge";
import type { AnalysisMode, BrowserSession, Job, ProxySettings } from "../types";

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

const emptyProxy: ProxySettings = {
  mode: "direct", protocol: "https", country_code: "CN", pool_size: 5, manual_proxy: "", active_proxy: null,
  active_source: "direct", exit_ip: null, latency_ms: null, last_checked_at: null, last_error: null,
  pool_provider: "smart", platform_scope: "taptap", allow_tls_interception: false, auto_rotate_on_risk: true,
  risk_rotation_limit: 2, zdopen_app_id: "", zdopen_configured: false, active_provider: null, tls_intercepted: false,
  target_results: {},
  pool_api: "https://proxy.scdn.io/api/get_proxy.php",
  pool_apis: { scdn: "https://proxy.scdn.io/api/get_proxy.php", zdopen: "http://www.zdopen.com/FreeProxy/Get/" }
};

const proxyModeLabel = { direct: "服务器直连", manual: "手动代理", auto: "自动代理池" } as const;

export default function Dashboard() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [sessions, setSessions] = useState<Record<Platform, BrowserSession>>({
    bilibili: emptySession("bilibili"),
    taptap: emptySession("taptap")
  });
  const [proxy, setProxy] = useState<ProxySettings>(emptyProxy);
  const [workspace, setWorkspace] = useState<Platform | null>(null);
  const [keyword, setKeyword] = useState("");
  const [officialUrl, setOfficialUrl] = useState("");
  const [taptapUrl, setTapTapUrl] = useState("");
  const [includeDiscovery, setIncludeDiscovery] = useState(true);
  const [includeTapTap, setIncludeTapTap] = useState(true);
  const [timeRange, setTimeRange] = useState("90d");
  const [depth, setDepth] = useState("standard");
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("lightweight");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [jobRows, bilibili, taptap, route] = await Promise.all([
      api.jobs(),
      api.platformSession("bilibili"),
      api.platformSession("taptap"),
      api.proxySettings()
    ]);
    setJobs(jobRows);
    setSessions({ bilibili, taptap });
    setProxy(route);
  }, []);

  useEffect(() => {
    void refresh().catch((err: Error) => setError(err.message));
    const timer = window.setInterval(() => void refresh().catch(() => undefined), 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  function connect(platform: Platform) {
    setError("");
    setWorkspace(platform);
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
    <div className="workspace workbench">
      <header className="workbench-header">
        <div><p className="eyebrow">OPINION SIGNAL DESK</p><h1>舆情任务台</h1><p className="workspace-lede">编排官号、相关视频与玩家评价采集</p></div>
        <div className="desk-state"><Radio size={16} /><span>单任务通道</span><small>页面采集 · 智能路由分析</small></div>
      </header>

      <section className="signal-rail" aria-label="数据源与网络状态">
        <div className="signal-rail-label"><MessageSquareText size={17} /><span>信号通道</span></div>
        <div className="platform-connections">
          {(["bilibili", "taptap"] as Platform[]).map((platform) => {
            const session = sessions[platform];
            const label = platform === "bilibili" ? "B站" : "TapTap";
            return <div className={`connection signal-channel signal-${platform} ${session.authenticated ? "connected" : ""}`} key={platform}>
              <span className="signal-index">{platform === "bilibili" ? "BI" : "TT"}</span>
              <div><strong>{label}{session.authenticated ? "已连接" : "未连接"}</strong><small>{session.message}</small></div>
              <button className="icon-button" title={`打开 ${label} 页面子窗口`} onClick={() => connect(platform)}><Cable size={17} /></button>
              {session.running && <button className="icon-button danger" title={`清除 ${label} 登录资料`} onClick={() => void disconnect(platform)}><LogOut size={17} /></button>}
            </div>;
          })}
        </div>
        <div className={`signal-channel signal-proxy ${proxy.last_error ? "route-warning" : ""}`}>
          <span className="signal-index"><Route size={16} /></span>
          <div><strong>{proxyModeLabel[proxy.mode]}</strong><small>{proxy.exit_ip ? `出口 ${proxy.exit_ip}${proxy.latency_ms != null ? ` · ${proxy.latency_ms} ms` : ""}` : proxy.active_proxy || "当前未使用代理"}</small></div>
          <Link className="icon-button" to="/settings" title="管理网络路由"><ChevronRight size={18} /></Link>
        </div>
      </section>

      {error && <div className="alert error-alert">{error}</div>}

      <section className="task-composer launch-panel">
        <div className="section-heading"><div><p className="panel-kicker">NEW RUN</p><h2>启动采集</h2></div><span>官号与相关视频独立分析，最终统一汇总</span></div>
        <form onSubmit={submit} className="launch-form">
          <div className="launch-core">
            <label className="field keyword-field"><span>分析关键词</span><input value={keyword} onChange={(event) => setKeyword(event.target.value)} minLength={2} maxLength={64} required placeholder="输入游戏、产品或事件" /></label>
            <button className="button primary start-button" disabled={loading || keyword.trim().length < 2 || (!officialUrl && !includeDiscovery && !includeTapTap)}>{loading ? <LoaderCircle className="spin" size={18} /> : <ScanSearch size={18} />}开始采集与分析</button>
          </div>

          <div className="source-grid">
            <label className="field source-field official-source"><span><i />B站官号</span><input value={officialUrl} onChange={(event) => setOfficialUrl(event.target.value)} placeholder="https://space.bilibili.com/3546785396034301" /></label>
            <div className={`source-choice discovery-source ${includeDiscovery ? "selected" : ""}`}><label><input type="checkbox" checked={includeDiscovery} onChange={(event) => setIncludeDiscovery(event.target.checked)} /><span>搜索 B站相关视频</span></label><small>与官号视频按 BVID 去重</small></div>
            <div className={`source-choice taptap-source ${includeTapTap ? "selected" : ""}`}><label><input type="checkbox" checked={includeTapTap} onChange={(event) => setIncludeTapTap(event.target.checked)} /><span>采集 TapTap 评价</span></label><input aria-label="TapTap 应用地址" value={taptapUrl} onChange={(event) => setTapTapUrl(event.target.value)} placeholder="应用地址（可选）" disabled={!includeTapTap} /></div>
          </div>

          <div className="run-options">
            <label className="field"><span>时间范围</span><select value={timeRange} onChange={(event) => setTimeRange(event.target.value)}><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="180d">近 180 天</option><option value="all">全部</option></select></label>
            <label className="field"><span>采集深度</span><select value={depth} onChange={(event) => setDepth(event.target.value)}><option value="light">轻量</option><option value="standard">标准</option><option value="deep">深度</option></select></label>
            <fieldset className="field mode-field"><legend>分析模式</legend><div className="segmented three-way"><button type="button" className={analysisMode === "local" ? "active" : ""} onClick={() => setAnalysisMode("local")}>本地</button><button type="button" className={analysisMode === "lightweight" ? "active" : ""} onClick={() => setAnalysisMode("lightweight")}>轻量 LLM</button><button type="button" className={analysisMode === "full" ? "active" : ""} onClick={() => setAnalysisMode("full")}>全量 LLM</button></div></fieldset>
          </div>
        </form>
      </section>

      <section className="task-history">
        <div className="section-heading"><div><p className="panel-kicker">RUN LEDGER</p><h2>历史任务</h2></div><button className="icon-button" title="刷新任务" onClick={() => void refresh()}><RefreshCw size={17} /></button></div>
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
