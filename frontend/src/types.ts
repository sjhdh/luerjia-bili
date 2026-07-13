export type JobStatus =
  | "pending"
  | "awaiting_login"
  | "collecting"
  | "awaiting_taptap_selection"
  | "analyzing"
  | "rendering"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";

export interface Job {
  id: string;
  keyword: string;
  status: JobStatus;
  stage: string;
  progress: number;
  message: string;
  analysis_mode: "local" | "enhanced";
  time_range: string;
  depth: string;
  taptap_app_id: string | null;
  taptap_candidates: Array<{
    id: string;
    title: string;
    url: string;
    cover_url?: string | null;
    match_score: number;
  }>;
  warnings: string[];
  partial: boolean;
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface BrowserSession {
  running: boolean;
  authenticated: boolean;
  login_method: "window" | "qr";
  qr_ready: boolean;
  qr_expires_at: string | null;
  message: string;
}

export interface DistributionItem {
  name: "positive" | "neutral" | "negative";
  label: string;
  count: number;
  percentage: number;
}

export interface ReportPayload {
  id: string;
  keyword: string;
  generated_at: string;
  partial: boolean;
  warnings: string[];
  hero: { cover_url: string | null; subtitle: string };
  metrics: {
    video_count: number;
    selected_video_count: number;
    comment_count: number;
    danmaku_count: number;
    review_count: number;
    taptap_score: number | null;
    overall_positive: number;
    overall_neutral: number;
    overall_negative: number;
  };
  sentiment: Record<"overall" | "bilibili" | "taptap", { total: number; items: DistributionItem[] }>;
  rating_distribution: Array<{ star: number; count: number; percentage: number }>;
  timeline: Array<{ date: string; positive: number; neutral: number; negative: number; total: number }>;
  keywords: Array<{ word: string; count: number; negative_ratio: number }>;
  tags: Array<{ name: string; count: number }>;
  topics: Array<{
    id: number;
    name: string;
    keywords: string[];
    size: number;
    negative_ratio: number;
    risk_score: number;
    samples: string[];
  }>;
  samples: Record<"positive" | "neutral" | "negative", Sample[]>;
  videos: VideoRow[];
  source_app: { id: string; title: string; url: string; score: number | null; rating_count: number } | null;
  model_quality: {
    sample_size: number;
    accuracy: number | null;
    macro_f1: number | null;
    labels?: string[];
    confusion: number[][];
    model: string;
    revision: string;
  };
  summary: {
    overview: string;
    positives: string[];
    risks: string[];
    recommendations: string[];
    enhanced?: boolean;
  };
  methodology: Record<string, string>;
}

export interface Sample {
  id: number;
  platform: string;
  kind: string;
  author: string;
  text: string;
  rating: number | null;
  likes: number;
  confidence: number | null;
}

export interface VideoRow {
  id: string;
  title: string;
  url: string;
  cover_url: string | null;
  creator: string | null;
  views: number;
  likes: number;
  coins: number;
  favorites: number;
  replies: number;
  danmakus: number;
  selection_score: number;
  selected: boolean;
  score_components: Record<string, number>;
}
