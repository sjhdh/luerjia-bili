import type { JobStatus } from "../types";

const labels: Record<JobStatus, string> = {
  pending: "等待中",
  awaiting_login: "等待登录",
  collecting: "采集中",
  awaiting_taptap_selection: "待选应用",
  analyzing: "分析中",
  rendering: "生成报告",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
  cancelled: "已取消"
};

export default function StatusBadge({ status }: { status: JobStatus }) {
  return <span className={`status status-${status}`}>{labels[status]}</span>;
}
