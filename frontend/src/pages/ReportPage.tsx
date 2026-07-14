import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { AlertTriangle, ArrowLeft, Check, Copy, DatabaseZap, Download, FileSpreadsheet, Heart, MessageCircle, Share2, ShieldAlert, Sparkles, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import ChartPanel from "../components/ChartPanel";
import type { Distribution, DistributionItem, ReportPayload, ReportSection, Sample, ShareLink, VideoRow } from "../types";

const colors = { positive: "#168a62", neutral: "#d7922d", negative: "#d84a5b", pink: "#fb7299", blue: "#00a6ff" };
const compact = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });

function isReportCover(value: string | null | undefined): value is string {
  return Boolean(value && !/favicon(?:\.|\/)/i.test(value));
}

function sentimentOption(items: DistributionItem[]): EChartsOption {
  return { tooltip: { trigger: "item", formatter: "{b}: {d}%" }, legend: { bottom: 0 }, series: [{ type: "pie", radius: ["48%", "72%"], center: ["50%", "44%"], itemStyle: { borderColor: "#fff", borderWidth: 3 }, label: { formatter: "{b}\n{d}%" }, data: items.map((item) => ({ name: item.label, value: item.percentage, itemStyle: { color: colors[item.name] } })) }] };
}

function timelineOption(rows: ReportSection["timeline"]): EChartsOption {
  return { tooltip: { trigger: "axis" }, legend: { bottom: 0 }, grid: { left: 42, right: 18, top: 28, bottom: 48 }, xAxis: { type: "category", data: rows.map((row) => row.date.slice(5)) }, yAxis: { type: "value" }, series: (["positive", "neutral", "negative"] as const).map((key) => ({ name: key === "positive" ? "正面" : key === "neutral" ? "中性" : "负面", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row[key]), itemStyle: { color: colors[key] } })) };
}

function keywordOption(rows: ReportSection["keywords"]): EChartsOption {
  const values = rows.slice(0, 15);
  return { tooltip: { trigger: "axis" }, grid: { left: 76, right: 20, top: 10, bottom: 20 }, xAxis: { type: "value" }, yAxis: { type: "category", inverse: true, data: values.map((row) => row.word) }, series: [{ type: "bar", data: values.map((row) => ({ value: row.count, itemStyle: { color: row.negative_ratio > 0.5 ? colors.negative : colors.blue } })), barMaxWidth: 18 }] };
}

function ratingOption(rows: NonNullable<ReportSection["rating_distribution"]>): EChartsOption {
  return { tooltip: { trigger: "axis" }, grid: { left: 42, right: 16, top: 20, bottom: 35 }, xAxis: { type: "category", data: rows.map((row) => `${row.star}星`) }, yAxis: { type: "value" }, series: [{ type: "bar", data: rows.map((row) => row.count), itemStyle: { color: colors.pink }, barMaxWidth: 44 }] };
}

function Samples({ items, tone }: { items: Sample[]; tone: "positive" | "neutral" | "negative" }) {
  return <div className="sample-list">{items.length ? items.slice(0, 4).map((item) => <article className={`sample sample-${tone}`} key={item.id}><div className="sample-meta"><strong>{item.rating ? "★".repeat(item.rating) + "☆".repeat(5 - item.rating) : item.author}</strong><span>{item.kind === "review" ? "TapTap" : item.kind === "danmaku" ? "B站弹幕" : item.reply_depth ? "楼中楼" : "B站评论"} · {compact.format(item.likes)} 赞</span></div><p>{item.text}</p></article>) : <div className="empty-state">暂无样本</div>}</div>;
}

function VideoTable({ videos, official }: { videos: VideoRow[]; official: boolean }) {
  const rows = official ? videos : videos.filter((video) => video.selected);
  if (!rows.length) return null;
  return <div className="video-table"><table><thead><tr><th>视频</th><th>发布时间</th><th>播放</th><th>点赞</th><th>投币</th><th>收藏</th><th>评论</th><th>弹幕</th></tr></thead><tbody>{rows.map((video) => <tr key={video.id}><td><a href={video.url} target="_blank" rel="noreferrer">{video.cover_url && <img src={video.cover_url} alt="" />}<span><strong>{video.title}</strong><small>{video.creator || video.id}</small></span></a></td><td>{video.published_at ? new Date(video.published_at).toLocaleDateString("zh-CN") : "--"}</td><td>{compact.format(video.views)}</td><td>{compact.format(video.likes)}</td><td>{compact.format(video.coins)}</td><td>{compact.format(video.favorites)}</td><td>{compact.format(video.replies)}</td><td>{compact.format(video.danmakus)}</td></tr>)}</tbody></table></div>;
}

function SourceSection({ section }: { section: ReportSection }) {
  const isOfficial = section.key === "bilibili_official";
  const isTapTap = section.key === "taptap";
  if (!section.available) {
    return <section id={section.key} className={`source-report source-report-${section.key}`}><header className="source-report-header"><div><p>{isTapTap ? "TAPTAP" : "BILIBILI"}</p><h2>{section.label}</h2></div><span>无有效样本</span></header><div className="source-empty"><DatabaseZap size={24} /><p>该来源未采集到可分析内容，未计算情感比例。</p></div></section>;
  }
  return <section id={section.key} className={`source-report source-report-${section.key}`}>
    <header className="source-report-header"><div><p>{isTapTap ? "TAPTAP" : "BILIBILI"}</p><h2>{section.label}</h2></div><div className="source-metrics"><span><strong>{section.metrics.sample_count}</strong>样本</span>{section.metrics.video_count > 0 && <span><strong>{section.metrics.video_count}</strong>视频</span>}{section.metrics.nested_reply_count > 0 && <span><strong>{section.metrics.nested_reply_count}</strong>楼中楼</span>}</div></header>
    <div className="report-grid two-columns"><ChartPanel title="情感占比" subtitle={`${section.sentiment.estimated ? "轻量 LLM 分层校准估计 · " : ""}${section.metrics.sample_count} 条有效样本`} option={sentimentOption(section.sentiment.items)} />{isTapTap && section.rating_distribution ? <ChartPanel title="星级分布" subtitle="星级作为权威情感标签" option={ratingOption(section.rating_distribution)} /> : <ChartPanel title="情感变化趋势" subtitle="按可用发布时间聚合" option={timelineOption(section.timeline)} />}</div>
    {isTapTap && <ChartPanel title="情感变化趋势" subtitle="按可用发布时间聚合" option={timelineOption(section.timeline)} />}
    <div className="report-grid two-columns"><ChartPanel title="高频讨论词" subtitle="TOP 15" option={keywordOption(section.keywords)} /><section className="report-panel"><div className="panel-heading"><h3>{isTapTap ? "官方标签" : "风险议题"}</h3><p>{isTapTap ? "TapTap 页面公开标签" : "负面占比与互动综合排序"}</p></div>{isTapTap ? <div className="tag-cloud">{section.tags?.length ? section.tags.slice(0, 18).map((tag) => <span key={tag.name}><b>{tag.name}</b>{compact.format(tag.count)}</span>) : <div className="empty-state">暂无标签</div>}</div> : <div className="risk-list compact-risk-list">{section.topics.slice(0, 6).map((topic, index) => <article className="risk-row" key={topic.id}><span className="risk-rank">{String(index + 1).padStart(2, "0")}</span><div><strong>{topic.name}</strong><p>{topic.keywords.join(" · ")}</p></div><div className="risk-bar"><span style={{ width: `${Math.min(100, topic.negative_ratio)}%` }} /></div><b>{topic.negative_ratio}%</b><small>{topic.size} 条</small></article>)}</div>}</section></div>
    <div className="section-sample-grid"><section><div className="panel-heading"><h3>正面样本</h3></div><Samples items={section.samples.positive} tone="positive" /></section><section><div className="panel-heading"><h3>负面样本</h3></div><Samples items={section.samples.negative} tone="negative" /></section><section><div className="panel-heading"><h3>中性样本</h3></div><Samples items={section.samples.neutral} tone="neutral" /></section></div>
    <VideoTable videos={section.videos} official={isOfficial} />
    <div className="section-summary"><strong>{section.summary.overview}</strong><span>{section.summary.risks.slice(0, 2).join("；")}</span></div>
  </section>;
}

function fallbackSection(report: ReportPayload, key: ReportSection["key"], label: string, distribution: Distribution, available: boolean): ReportSection {
  const isTapTap = key === "taptap";
  return { key, label, available, metrics: { sample_count: distribution.total, comment_count: isTapTap ? 0 : report.metrics.comment_count, nested_reply_count: 0, danmaku_count: isTapTap ? 0 : report.metrics.danmaku_count, review_count: isTapTap ? report.metrics.review_count : 0, video_count: isTapTap ? 0 : report.metrics.video_count }, sentiment: distribution, timeline: report.timeline, keywords: report.keywords, topics: report.topics, samples: { positive: report.samples.positive.filter((item) => isTapTap ? item.platform === "taptap" : item.platform === "bilibili"), neutral: report.samples.neutral.filter((item) => isTapTap ? item.platform === "taptap" : item.platform === "bilibili"), negative: report.samples.negative.filter((item) => isTapTap ? item.platform === "taptap" : item.platform === "bilibili") }, videos: isTapTap ? [] : report.videos, summary: report.summary, rating_distribution: isTapTap ? report.rating_distribution : undefined, tags: isTapTap ? report.tags : undefined };
}

function AIReport({ report }: { report: ReportPayload }) {
  const analysis = report.ai_analysis;
  if (!analysis) return null;
  const coverage = report.analysis?.llm_coverage;
  const routeRatio = report.analysis?.llm_route_ratio;
  const successRate = report.analysis?.llm_success_rate;
  const evidence = new Map((analysis.evidence || []).map((item) => [item.id, item]));
  const Evidence = ({ ids }: { ids?: number[] }) => {
    const rows = (ids || []).map((id) => evidence.get(id)).filter((item) => item != null).slice(0, 2);
    return rows.length ? <div className="ai-evidence-list">{rows.map((item) => <blockquote key={item.id}><p>{item.text}</p><span>证据 #{item.id} · {item.source_scope === "bilibili_official" ? "B站官号" : item.source_scope === "bilibili_discovery" ? "B站相关视频" : "TapTap"} · {compact.format(item.likes)} 赞</span></blockquote>)}</div> : null;
  };
  return <section className="ai-analysis-section">
    <header className="ai-analysis-header"><div><p className="panel-kicker">GPT-5.6 COMPOSITE REVIEW</p><h2><Sparkles size={21} />AI 深度研判</h2></div><div className="ai-analysis-meta"><span>{analysis.model}</span>{report.analysis?.mode === "lightweight" && routeRatio != null ? <strong>智能送审 {(routeRatio * 100).toFixed(1)}%</strong> : coverage != null && <strong>文本覆盖 {(coverage * 100).toFixed(1)}%</strong>}{successRate != null && <small>送审成功 {(successRate * 100).toFixed(1)}%</small>}<small>{analysis.prompt_version}</small></div></header>
    <p className="ai-executive-summary">{analysis.executive_summary}</p>
    <div className="ai-insight-grid">
      <section className="ai-insight-list finding-list"><div className="panel-heading"><h3>关键发现</h3><p>基于统计与高互动证据</p></div>{analysis.findings.map((item, index) => <article key={`${item.title}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{item.title}</strong><p>{item.detail}</p><Evidence ids={item.evidence_ids} /></div></article>)}</section>
      <section className="ai-insight-list risk-list-ai"><div className="panel-heading"><h3>重点风险</h3><p>风险排序不是用户概率</p></div>{analysis.risks.map((item, index) => <article key={`${item.title}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{item.title}</strong><p>{item.detail}</p><Evidence ids={item.evidence_ids} /></div></article>)}</section>
    </div>
    <section className="ai-action-plan"><div className="panel-heading"><h3>行动优先级</h3><p>产品、运营与社区治理</p></div>{analysis.actions.map((item, index) => <article key={`${item.priority}-${item.title}-${index}`}><b className={`priority priority-${item.priority.toLowerCase()}`}>{item.priority}</b><div><strong>{item.title}</strong><p>{item.rationale}</p></div><span>{item.action}</span></article>)}</section>
    {analysis.caveats.length > 0 && <footer className="ai-caveats"><ShieldAlert size={17} /><div><strong>解读边界</strong><p>{analysis.caveats.join("；")}</p></div></footer>}
  </section>;
}

export default function ReportPage() {
  const { jobId = "", shareToken = "" } = useParams();
  const shared = Boolean(shareToken);
  const [report, setReport] = useState<ReportPayload | null>(null);
  const [error, setError] = useState("");
  const [share, setShare] = useState<ShareLink | null>(null);
  const [shareBusy, setShareBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => { void (shared ? api.sharedReport(shareToken) : api.report(jobId)).then(setReport).catch((err: Error) => setError(err.message)); }, [jobId, shareToken, shared]);

  const sections = useMemo(() => {
    if (!report) return [];
    if (report.sections) return [report.sections.bilibili_official, report.sections.bilibili_discovery, report.sections.taptap];
    const empty: Distribution = { total: 0, available: false, items: report.sentiment.bilibili.items.map((item) => ({ ...item, count: 0, percentage: 0 })) };
    return [fallbackSection(report, "bilibili_official", "B站官号", empty, false), fallbackSection(report, "bilibili_discovery", "B站相关视频", report.sentiment.bilibili, report.sentiment.bilibili.total > 0), fallbackSection(report, "taptap", "TapTap 玩家评价", report.sentiment.taptap, report.sentiment.taptap.total > 0)];
  }, [report]);

  async function createShare() {
    setShareBusy(true);
    try { setShare(await api.createShare(jobId)); } catch (err) { setError((err as Error).message); }
    finally { setShareBusy(false); }
  }

  async function copyShare() {
    if (!share) return;
    await navigator.clipboard.writeText(share.url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  if (error) return <div className="workspace"><div className="alert error-alert">{error}</div></div>;
  if (!report) return <div className="loading-page">加载报告</div>;

  const discovery = sections.find((section) => section.key === "bilibili_discovery");
  const selectedDiscoveryCount = discovery?.videos.filter((video) => video.selected).length
    || report.metrics.discovery_video_count
    || report.metrics.selected_video_count;
  const heroCover = isReportCover(report.hero.cover_url)
    ? report.hero.cover_url
    : report.videos.find((video) => isReportCover(video.cover_url))?.cover_url;
  const missingRequestedSource = Boolean(report.data_quality?.empty_sources.length);
  const qualityLabel = report.data_quality?.valid === false
    ? missingRequestedSource ? "部分来源缺少样本" : "部分采集未完整"
    : "数据质量检查通过";
  const lightweightEstimate = report.analysis?.mode === "lightweight" && report.sentiment.overall.estimated;

  return <article className="report-page">
    {!shared && <div className="report-toolbar no-print"><Link to={`/jobs/${jobId}`} className="back-link"><ArrowLeft size={17} />返回任务</Link><div><button className="button secondary" onClick={() => void createShare()} disabled={shareBusy}><Share2 size={17} />分享</button><a className="button secondary" href={`/api/v1/reports/${jobId}/export.csv`}><FileSpreadsheet size={17} />CSV</a><a className="button primary" href={`/api/v1/reports/${jobId}/export.pdf`}><Download size={17} />PDF</a></div></div>}
    <header className="report-hero"><div className="hero-content"><div><p className="hero-kicker">跨平台舆情报告</p><h1>《{report.keyword}》舆情分析</h1><p>{report.hero.subtitle}</p><div className="hero-chips"><span>官号 {report.metrics.official_video_count ?? 0} 个视频</span><span>相关视频 {selectedDiscoveryCount} 个</span><span>TapTap {report.metrics.review_count} 条评价</span></div><small>生成于 {new Date(report.generated_at).toLocaleString("zh-CN")} · {shared ? "匿名只读分享" : "内部工作台"}</small></div>{heroCover && <img className="hero-cover" src={heroCover} alt={report.keyword} />}</div></header>
    {report.warnings.length > 0 && <div className="report-alert"><AlertTriangle size={18} />{report.warnings.join("；")}</div>}
    <section className="metric-grid"><div className="metric metric-score"><strong>{report.metrics.taptap_score?.toFixed(1) ?? "--"}</strong><span>TapTap 评分</span><small>{report.source_app?.rating_count ? `${compact.format(report.source_app.rating_count)} 条全量评价` : "暂无评分"}</small></div><div className="metric metric-positive"><strong>{report.sentiment.overall.total ? `${report.metrics.overall_positive}%` : "--"}</strong><span>正面</span><small>{lightweightEstimate ? "分层校准估计 · 平台等权" : "平台等权"}</small></div><div className="metric metric-neutral"><strong>{report.sentiment.overall.total ? `${report.metrics.overall_neutral}%` : "--"}</strong><span>中性</span><small>{lightweightEstimate ? "分层校准估计 · 平台等权" : "平台等权"}</small></div><div className="metric metric-negative"><strong>{report.sentiment.overall.total ? `${report.metrics.overall_negative}%` : "--"}</strong><span>负面</span><small>{lightweightEstimate ? "分层校准估计 · 平台等权" : "平台等权"}</small></div></section>
    <div className={`quality-strip ${report.data_quality?.valid === false ? "quality-warning" : ""}`}><DatabaseZap size={18} /><div><strong>{qualityLabel}</strong><span>{report.data_quality?.sample_count ?? report.sentiment.overall.total} 条有效样本 · 官号与相关视频已按 BVID 去重</span></div></div>
    <div className="report-grid two-columns"><ChartPanel title="跨平台情感占比" subtitle={lightweightEstimate ? "轻量 LLM 分层校准估计 · 平台等权" : "B站与 TapTap 平台等权"} option={sentimentOption(report.sentiment.overall.items)} /><section className="summary-section overall-summary"><div className="summary-title"><Sparkles size={22} /><div><h2>综合结论</h2><p>{report.analysis?.mode === "lightweight" ? "轻量 LLM" : report.analysis?.mode === "full" ? "全量 LLM" : "本地模型"}</p></div></div><p className="summary-overview">{report.summary.overview}</p><div className="summary-lines"><p><Heart size={16} />{report.summary.positives.slice(0, 2).join("；")}</p><p><AlertTriangle size={16} />{report.summary.risks.slice(0, 2).join("；")}</p><p><MessageCircle size={16} />{report.summary.recommendations.slice(0, 2).join("；")}</p></div></section></div>
    <nav className="report-source-nav no-print">{sections.map((section) => <a key={section.key} href={`#${section.key}`} className={section.available ? "" : "disabled"}><span className={`source-dot source-${section.key === "taptap" ? "taptap" : "bilibili"}`} />{section.label}<small>{section.metrics.sample_count}</small></a>)}</nav>
    {sections.map((section) => <SourceSection key={section.key} section={section} />)}
    <AIReport report={report} />
    <section className="model-section">
      <div className="panel-heading"><h2>分析质量</h2><p>{report.model_quality.llm_coverage != null ? report.analysis?.mode === "lightweight" ? "智能路由、分层校准与本地基线一致性" : "GPT-5.6 覆盖与本地基线一致性" : "TapTap 星级标签校准"}</p></div>
      <div className={`model-metrics ${report.analysis?.mode === "lightweight" ? "four" : ""}`}>
        {report.model_quality.llm_coverage != null ? <>
          <span><strong>{report.analysis?.mode === "lightweight" && report.analysis.llm_route_ratio != null ? `${(report.analysis.llm_route_ratio * 100).toFixed(1)}%` : `${(report.model_quality.llm_coverage * 100).toFixed(1)}%`}</strong>{report.analysis?.mode === "lightweight" ? "LLM 送审率" : "GPT 覆盖"}</span>
          {report.analysis?.mode === "lightweight" && <span><strong>{report.analysis.sentiment_calibration_sample_size ?? "--"}</strong>分层校准样本</span>}
          <span><strong>{report.model_quality.local_llm_agreement != null ? `${(report.model_quality.local_llm_agreement * 100).toFixed(1)}%` : "--"}</strong>本地一致率</span>
          <span><strong>{report.analysis?.llm_success_rate != null ? `${(report.analysis.llm_success_rate * 100).toFixed(1)}%` : report.model_quality.llm_covered_count ?? 0}</strong>{report.analysis?.llm_success_rate != null ? "送审成功率" : "复核文本"}</span>
        </> : <>
          <span><strong>{report.model_quality.sample_size}</strong>校准样本</span>
          <span><strong>{report.model_quality.accuracy != null ? `${(report.model_quality.accuracy * 100).toFixed(1)}%` : "--"}</strong>准确率</span>
          <span><strong>{report.model_quality.macro_f1 != null ? report.model_quality.macro_f1.toFixed(3) : "--"}</strong>Macro F1</span>
        </>}
      </div>
      <small>{report.model_quality.model} · {report.model_quality.revision.slice(0, 24)}</small>
    </section>
    <footer className="methodology"><h2>合规与方法说明</h2>{Object.values(report.methodology).map((text) => <p key={text}>{text}</p>)}</footer>
    {share && <div className="share-overlay no-print" role="dialog" aria-modal="true" aria-label="报告分享"><section className="share-dialog"><button className="icon-button share-close" title="关闭" onClick={() => setShare(null)}><X size={18} /></button><div className="share-icon"><Share2 size={22} /></div><h2>只读分享链接</h2><p>链接于 {new Date(share.expires_at).toLocaleString("zh-CN")} 过期。</p><div className="share-value"><input readOnly value={share.url} /><button className="button primary" onClick={() => void copyShare()}>{copied ? <Check size={17} /> : <Copy size={17} />}{copied ? "已复制" : "复制"}</button></div><small><ShieldAlert size={14} />仅包含匿名化报告，不开放原始 CSV。</small></section></div>}
  </article>;
}
