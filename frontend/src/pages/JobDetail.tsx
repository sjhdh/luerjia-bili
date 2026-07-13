import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, BarChart3, LoaderCircle, RefreshCw, RotateCcw, Square } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import StatusBadge from "../components/StatusBadge";
import type { Job } from "../types";

export default function JobDetail() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => setJob(await api.job(jobId)), [jobId]);

  useEffect(() => {
    void load().catch((err: Error) => setError(err.message));
    const stream = new EventSource(`/api/v1/jobs/${jobId}/events`);
    stream.onmessage = (event) => setJob(JSON.parse(event.data) as Job);
    stream.onerror = () => stream.close();
    return () => stream.close();
  }, [jobId, load]);

  async function act(action: () => Promise<Job>) {
    setBusy(true); setError("");
    try { setJob(await action()); } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  if (!job) return <div className="loading-page"><LoaderCircle className="spin" />加载任务</div>;
  const running = ["pending", "collecting", "analyzing", "rendering"].includes(job.status);
  const reportReady = ["completed", "partial"].includes(job.status);

  return (
    <div className="workspace narrow-workspace">
      <div className="detail-nav"><Link to="/" className="back-link"><ArrowLeft size={17} />返回任务</Link><button className="icon-button" title="刷新" onClick={() => void load()}><RefreshCw size={17} /></button></div>
      {error && <div className="alert error-alert">{error}</div>}
      <section className="job-summary">
        <div className="job-title-row"><div><p className="eyebrow">关键词分析</p><h1>{job.keyword}</h1></div><StatusBadge status={job.status} /></div>
        <div className="large-progress"><span style={{ width: `${job.progress}%` }} /></div>
        <div className="progress-caption"><strong>{job.stage}</strong><span>{job.progress}%</span></div>
        <p className="job-message">{job.message || "任务已进入队列"}</p>
        {job.warnings.length > 0 && <div className="warning-list">{job.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
        <div className="job-actions">
          {running && <button className="button danger-button" disabled={busy} onClick={() => void act(() => api.cancelJob(job.id))}><Square size={16} />取消</button>}
          {["failed", "cancelled", "awaiting_login"].includes(job.status) && <button className="button secondary" disabled={busy} onClick={() => void act(() => api.retryJob(job.id))}><RotateCcw size={17} />重试</button>}
          {reportReady && <><button className="button primary" onClick={() => navigate(`/reports/${job.id}`)}><BarChart3 size={17} />查看报告</button><button className="button secondary" disabled={busy} onClick={() => void act(() => api.rerunJob(job.id))}><RotateCcw size={17} />重新分析</button></>}
        </div>
      </section>

      {job.status === "awaiting_taptap_selection" && (
        <section className="candidate-section"><div className="section-heading"><h2>选择 TapTap 应用</h2><span>匹配结果需要确认</span></div><div className="candidate-list">{job.taptap_candidates.map((candidate) => (
          <button key={candidate.id} className="candidate" onClick={() => void act(() => api.selectTapTap(job.id, candidate.id))} disabled={busy}>{candidate.cover_url ? <img src={candidate.cover_url} alt="" /> : <span className="cover-placeholder" />}<span><strong>{candidate.title}</strong><small>匹配度 {(candidate.match_score * 100).toFixed(0)}%</small></span></button>
        ))}</div></section>
      )}
    </div>
  );
}
