import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, BarChart3, ExternalLink, LoaderCircle, MonitorUp, RefreshCw, RotateCcw, Sparkles, Square } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import BrowserWorkspace from "../components/BrowserWorkspace";
import StatusBadge from "../components/StatusBadge";
import type { AnalysisMode, Job } from "../types";

export default function JobDetail() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamVersion, setStreamVersion] = useState(0);
  const [workspace, setWorkspace] = useState<"bilibili" | "taptap" | null>(null);
  const [reanalysisMode, setReanalysisMode] = useState<AnalysisMode>("lightweight");
  const load = useCallback(async () => setJob(await api.job(jobId)), [jobId]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
    const stream = new EventSource(`/api/v1/jobs/${jobId}/events`);
    stream.onmessage = (event) => setJob(JSON.parse(event.data) as Job);
    stream.onerror = () => stream.close();
    return () => stream.close();
  }, [jobId, load, streamVersion]);

  async function act(action: () => Promise<Job>) {
    setBusy(true); setError("");
    try { setJob(await action()); setStreamVersion((current) => current + 1); } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  if (!job) return <div className="loading-page"><LoaderCircle className="spin" />加载任务</div>;
  const running = ["pending", "collecting", "analyzing", "rendering"].includes(job.status);
  const reportReady = ["completed", "partial"].includes(job.status)
    || (job.status === "cancelled" && job.collection_metrics.analysis_only === true);

  return (
    <div className="workspace narrow-workspace">
      <div className="detail-nav"><Link to="/" className="back-link"><ArrowLeft size={17} />返回任务</Link><button className="icon-button" title="刷新" onClick={() => void load()}><RefreshCw size={17} /></button></div>
      {error && <div className="alert error-alert">{error}</div>}
      <section className="job-summary">
        <div className="job-title-row"><div><p className="eyebrow">多来源分析</p><h1>{job.keyword}</h1></div><StatusBadge status={job.status} /></div>
        <div className="job-source-strip">
          {job.official_bilibili_url && <a href={job.official_bilibili_url} target="_blank" rel="noreferrer">B站官号 MID {job.official_mid}<ExternalLink size={13} /></a>}
          {job.include_discovery && <span>B站相关视频</span>}
          {job.include_taptap && <span>{job.taptap_app_id ? `TapTap ${job.taptap_app_id}` : "TapTap 自动匹配"}</span>}
        </div>
        <div className="large-progress"><span style={{ width: `${job.progress}%` }} /></div>
        <div className="progress-caption"><strong>{job.stage}</strong><span>{job.progress}%</span></div>
        <p className="job-message">{job.message || "任务已进入队列"}</p>
        {job.warnings.length > 0 && <div className="warning-list">{job.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
        <div className="job-actions">
          {running && <button className="button danger-button" disabled={busy} onClick={() => void act(() => api.cancelJob(job.id))}><Square size={16} />取消</button>}
          {job.status === "awaiting_login" && <button className="button primary" onClick={() => setWorkspace(job.stage.includes("TapTap") || job.message.includes("TapTap") ? "taptap" : "bilibili")}><MonitorUp size={17} />处理页面</button>}
          {["failed", "cancelled", "awaiting_login"].includes(job.status) && <button className="button secondary" disabled={busy} onClick={() => void act(() => api.retryJob(job.id))}><RotateCcw size={17} />重试</button>}
          {reportReady && <><button className="button primary" onClick={() => navigate(`/reports/${job.id}`)}><BarChart3 size={17} />查看报告</button><span className="reanalyze-control"><select aria-label="重新分析模式" value={reanalysisMode} onChange={(event) => setReanalysisMode(event.target.value as AnalysisMode)}><option value="local">本地</option><option value="lightweight">轻量 LLM</option><option value="full">全量 LLM</option></select><button className="button secondary ai-action" disabled={busy} onClick={() => void act(() => api.reanalyzeJob(job.id, reanalysisMode))}>{busy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}重新分析</button></span><button className="button secondary" disabled={busy} onClick={() => void act(() => api.rerunJob(job.id))}><RotateCcw size={17} />重新采集</button></>}
        </div>
      </section>

      {job.status === "awaiting_taptap_selection" && (
        <section className="candidate-section"><div className="section-heading"><h2>选择 TapTap 应用</h2><span>匹配结果需要确认</span></div><div className="candidate-list">{job.taptap_candidates.map((candidate) => (
          <button key={candidate.id} className="candidate" onClick={() => void act(() => api.selectTapTap(job.id, candidate.id))} disabled={busy}>{candidate.cover_url ? <img src={candidate.cover_url} alt="" /> : <span className="cover-placeholder" />}<span><strong>{candidate.title}</strong><small>匹配度 {(candidate.match_score * 100).toFixed(0)}%</small></span></button>
        ))}</div></section>
      )}
      <BrowserWorkspace platform={workspace || "bilibili"} open={workspace !== null} onClose={() => { setWorkspace(null); void load(); }} />
    </div>
  );
}
