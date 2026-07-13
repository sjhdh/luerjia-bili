import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { AlertTriangle, ArrowLeft, Download, FileSpreadsheet, Heart, MessageCircle, ShieldAlert, Sparkles } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import ChartPanel from "../components/ChartPanel";
import type { DistributionItem, ReportPayload, Sample } from "../types";

const colors = { positive: "#16855b", neutral: "#d89b22", negative: "#d94452", pink: "#e94b87", blue: "#2585d8" };
const compact = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });

function sentimentOption(items: DistributionItem[]): EChartsOption {
  return { tooltip: { trigger: "item", formatter: "{b}: {d}%" }, legend: { bottom: 0 }, series: [{ type: "pie", radius: ["48%", "72%"], center: ["50%", "44%"], itemStyle: { borderColor: "#fff", borderWidth: 3 }, label: { formatter: "{b}\n{d}%" }, data: items.map((item) => ({ name: item.label, value: item.percentage, itemStyle: { color: colors[item.name] } })) }] };
}

function Samples({ title, subtitle, items, tone }: { title: string; subtitle: string; items: Sample[]; tone: string }) {
  return <section className="sample-section"><div className="panel-heading"><h2>{title}</h2><p>{subtitle}</p></div><div className="sample-list">{items.length ? items.map((item) => <article className={`sample sample-${tone}`} key={item.id}><div className="sample-meta"><strong>{item.rating ? "★".repeat(item.rating) + "☆".repeat(5 - item.rating) : item.author}</strong><span>{item.platform === "taptap" ? "TapTap" : item.kind === "danmaku" ? "B站弹幕" : "B站评论"} · 👍 {item.likes}</span></div><p>{item.text}</p></article>) : <div className="empty-state">暂无样本</div>}</div></section>;
}

export default function ReportPage() {
  const { jobId = "" } = useParams();
  const [report, setReport] = useState<ReportPayload | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { void api.report(jobId).then(setReport).catch((err: Error) => setError(err.message)); }, [jobId]);
  const options = useMemo(() => {
    if (!report) return null;
    return {
      sentiment: sentimentOption(report.sentiment.overall.items),
      ratings: { tooltip: { trigger: "axis" }, grid: { left: 42, right: 16, top: 20, bottom: 35 }, xAxis: { type: "category", data: report.rating_distribution.map((row) => `${row.star}星`) }, yAxis: { type: "value" }, series: [{ type: "bar", data: report.rating_distribution.map((row) => row.count), itemStyle: { color: colors.pink }, barMaxWidth: 44 }] } satisfies EChartsOption,
      timeline: { tooltip: { trigger: "axis" }, legend: { bottom: 0 }, grid: { left: 42, right: 18, top: 28, bottom: 48 }, xAxis: { type: "category", data: report.timeline.map((row) => row.date.slice(5)) }, yAxis: { type: "value" }, series: ["positive", "neutral", "negative"].map((key) => ({ name: key === "positive" ? "正面" : key === "neutral" ? "中性" : "负面", type: "line", smooth: true, showSymbol: false, data: report.timeline.map((row) => row[key as keyof typeof row]), itemStyle: { color: colors[key as keyof typeof colors] } })) } satisfies EChartsOption,
      keywords: { tooltip: { trigger: "axis" }, grid: { left: 76, right: 20, top: 10, bottom: 20 }, xAxis: { type: "value" }, yAxis: { type: "category", inverse: true, data: report.keywords.slice(0, 15).map((row) => row.word) }, series: [{ type: "bar", data: report.keywords.slice(0, 15).map((row) => ({ value: row.count, itemStyle: { color: row.negative_ratio > 0.5 ? colors.negative : colors.blue } })), barMaxWidth: 18 }] } satisfies EChartsOption
    };
  }, [report]);

  if (error) return <div className="workspace"><div className="alert error-alert">{error}</div></div>;
  if (!report || !options) return <div className="loading-page">加载报告</div>;

  return (
    <article className="report-page">
      <div className="report-toolbar no-print"><Link to={`/jobs/${jobId}`} className="back-link"><ArrowLeft size={17} />返回任务</Link><div><a className="button secondary" href={`/api/v1/reports/${jobId}/export.csv`}><FileSpreadsheet size={17} />CSV</a><a className="button primary" href={`/api/v1/reports/${jobId}/export.pdf`}><Download size={17} />PDF</a></div></div>
      <header className="report-hero"><div className="hero-content"><div><p className="hero-kicker">双平台舆情报告</p><h1>《{report.keyword}》舆情分析</h1><p>{report.hero.subtitle}</p><div className="hero-chips"><span>B站 {report.metrics.selected_video_count} 个重点视频</span><span>{report.metrics.comment_count + report.metrics.danmaku_count} 条站内样本</span><span>TapTap {report.metrics.review_count} 条评价</span></div><small>生成于 {new Date(report.generated_at).toLocaleString("zh-CN")} · 本机可见页面采集</small></div>{report.hero.cover_url && <img className="hero-cover" src={report.hero.cover_url} alt={report.keyword} />}</div></header>
      {report.warnings.length > 0 && <div className="report-alert"><AlertTriangle size={18} />{report.warnings.join("；")}</div>}
      <section className="metric-grid"><div className="metric metric-score"><strong>{report.metrics.taptap_score?.toFixed(1) ?? "--"}</strong><span>TapTap 综合评分</span><small>{report.source_app?.rating_count ? `${compact.format(report.source_app.rating_count)} 条全量评价` : "暂无评分"}</small></div><div className="metric metric-positive"><strong>{report.metrics.overall_positive}%</strong><span>正面</span><small>平台等权</small></div><div className="metric metric-neutral"><strong>{report.metrics.overall_neutral}%</strong><span>中性</span><small>平台等权</small></div><div className="metric metric-negative"><strong>{report.metrics.overall_negative}%</strong><span>负面</span><small>平台等权</small></div></section>
      <div className="report-grid two-columns"><ChartPanel title="星级评分分布" subtitle={`TapTap 评价样本 ${report.metrics.review_count} 条`} option={options.ratings} /><ChartPanel title="舆情占比" subtitle="评论、可见弹幕与星级校准" option={options.sentiment} /></div>
      <ChartPanel title="情感变化趋势" subtitle="按可用发布时间聚合" option={options.timeline} />
      <div className="report-grid two-columns"><ChartPanel title="高频讨论词 TOP 15" subtitle="已去除通用停用词" option={options.keywords} /><section className="report-panel"><div className="panel-heading"><h2>官方议题标签</h2><p>TapTap 页面公开标签</p></div><div className="tag-cloud">{report.tags.length ? report.tags.slice(0, 18).map((tag) => <span key={tag.name}><b>{tag.name}</b>{compact.format(tag.count)}</span>) : <div className="empty-state">暂无标签</div>}</div></section></div>
      <section className="risk-section"><div className="panel-heading"><h2><ShieldAlert size={21} />核心风险议题</h2><p>负面占比、样本规模与互动量综合排序</p></div><div className="risk-list">{report.topics.slice(0, 6).map((topic, index) => <article className="risk-row" key={topic.id}><span className="risk-rank">{String(index + 1).padStart(2, "0")}</span><div><strong>{topic.name}</strong><p>{topic.keywords.join(" · ")}</p></div><div className="risk-bar"><span style={{ width: `${Math.min(100, topic.negative_ratio)}%` }} /></div><b>{topic.negative_ratio}% 负面</b><small>{topic.size} 条</small></article>)}</div></section>
      <Samples title="正面评价样本" subtitle="高置信度与高互动认可点" items={report.samples.positive} tone="positive" />
      <Samples title="负面评价样本" subtitle="优先复核的集中吐槽" items={report.samples.negative} tone="negative" />
      <Samples title="中性评价样本" subtitle="兼具认可与改进建议" items={report.samples.neutral} tone="neutral" />
      <section className="video-section"><div className="panel-heading"><h2>重点视频互动</h2><p>关键词、播放与互动综合加权</p></div><div className="video-table"><table><thead><tr><th>视频</th><th>播放</th><th>点赞</th><th>投币</th><th>收藏</th><th>评论</th><th>弹幕</th><th>权重</th></tr></thead><tbody>{report.videos.filter((video) => video.selected).map((video) => <tr key={video.id}><td><a href={video.url} target="_blank" rel="noreferrer">{video.cover_url && <img src={video.cover_url} alt="" />}<span><strong>{video.title}</strong><small>{video.creator || video.id}</small></span></a></td><td>{compact.format(video.views)}</td><td>{compact.format(video.likes)}</td><td>{compact.format(video.coins)}</td><td>{compact.format(video.favorites)}</td><td>{compact.format(video.replies)}</td><td>{compact.format(video.danmakus)}</td><td>{(video.selection_score * 100).toFixed(1)}</td></tr>)}</tbody></table></div></section>
      <section className="model-section"><div className="panel-heading"><h2>模型质量</h2><p>TapTap 星级标签校准</p></div><div className="model-metrics"><span><strong>{report.model_quality.sample_size}</strong>校准样本</span><span><strong>{report.model_quality.accuracy != null ? `${(report.model_quality.accuracy * 100).toFixed(1)}%` : "--"}</strong>准确率</span><span><strong>{report.model_quality.macro_f1 != null ? report.model_quality.macro_f1.toFixed(3) : "--"}</strong>Macro F1</span></div><small>{report.model_quality.model} · {report.model_quality.revision.slice(0, 12)}</small></section>
      <section className="summary-section"><div className="summary-title"><Sparkles size={22} /><div><h2>舆情总结</h2><p>{report.summary.enhanced ? "LLM 增强" : "本地模型"}</p></div></div><p className="summary-overview">{report.summary.overview}</p><div className="summary-grid"><div><h3><Heart size={17} />认可点</h3>{report.summary.positives.map((item) => <p key={item}>{item}</p>)}</div><div><h3><AlertTriangle size={17} />风险点</h3>{report.summary.risks.map((item) => <p key={item}>{item}</p>)}</div><div><h3><MessageCircle size={17} />行动建议</h3>{report.summary.recommendations.map((item) => <p key={item}>{item}</p>)}</div></div></section>
      <footer className="methodology"><h2>合规与方法说明</h2>{Object.values(report.methodology).map((text) => <p key={text}>{text}</p>)}</footer>
    </article>
  );
}
