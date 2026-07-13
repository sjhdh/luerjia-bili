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
  official_bilibili_url: string | null;
  official_mid: string | null;
  include_discovery: boolean;
  include_taptap: boolean;
  taptap_app_id: string | null;
  taptap_app_url: string | null;
  taptap_candidates: Array<{
    id: string;
    title: string;
    url: string;
    cover_url?: string | null;
    match_score: number;
  }>;
  collection_metrics: Record<string, unknown>;
  warnings: string[];
  partial: boolean;
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface BrowserSession {
  platform: "bilibili" | "taptap";
  running: boolean;
  authenticated: boolean;
  login_method: "window" | "qr";
  qr_ready: boolean;
  qr_expires_at: string | null;
  message: string;
  workspace_ready: boolean;
  current_url: string | null;
  page_title: string | null;
  risk_detected: boolean;
}

export interface AuthSession {
  authenticated: boolean;
  username: string | null;
}

export interface ShareLink {
  id: string;
  url: string;
  expires_at: string;
}

export interface DistributionItem {
  name: "positive" | "neutral" | "negative";
  label: string;
  count: number;
  percentage: number;
}

export interface Distribution {
  total: number;
  available?: boolean;
  items: DistributionItem[];
}

export interface ReportSection {
  key: "bilibili_official" | "bilibili_discovery" | "taptap";
  label: string;
  available: boolean;
  metrics: {
    sample_count: number;
    comment_count: number;
    nested_reply_count: number;
    danmaku_count: number;
    review_count: number;
    video_count: number;
  };
  sentiment: Distribution;
  timeline: Array<{ date: string; positive: number; neutral: number; negative: number; total: number }>;
  keywords: Array<{ word: string; count: number; negative_ratio: number }>;
  topics: ReportPayload["topics"];
  samples: Record<"positive" | "neutral" | "negative", Sample[]>;
  videos: VideoRow[];
  summary: ReportPayload["summary"];
  rating_distribution?: Array<{ star: number; count: number; percentage: number }>;
  tags?: Array<{ name: string; count: number }>;
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
    official_video_count?: number;
    discovery_video_count?: number;
    official_comment_count?: number;
    discovery_comment_count?: number;
    comment_count: number;
    danmaku_count: number;
    review_count: number;
    taptap_score: number | null;
    overall_positive: number;
    overall_neutral: number;
    overall_negative: number;
  };
  sentiment: Record<"overall" | "bilibili" | "taptap", Distribution> & Partial<Record<"bilibili_official" | "bilibili_discovery", Distribution>>;
  sections?: Record<"bilibili_official" | "bilibili_discovery" | "taptap", ReportSection>;
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
  official_account?: {
    mid: string;
    title: string;
    url: string;
    avatar_url: string | null;
    expected_video_count: number | null;
    collected_video_count: number;
  } | null;
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
  data_quality?: {
    valid: boolean;
    sample_count: number;
    requested_sources: Record<string, boolean>;
    available_sources: Record<string, boolean>;
    empty_sources: string[];
    collection: Record<string, unknown>;
  };
  methodology: Record<string, string>;
}

export interface Sample {
  id: number;
  platform: string;
  kind: string;
  source_scope: string;
  author: string;
  text: string;
  rating: number | null;
  likes: number;
  confidence: number | null;
  reply_depth?: number;
}

export interface VideoRow {
  id: string;
  title: string;
  url: string;
  cover_url: string | null;
  creator: string | null;
  published_at: string | null;
  views: number;
  likes: number;
  coins: number;
  favorites: number;
  replies: number;
  danmakus: number;
  selection_score: number;
  selected: boolean;
  source_scope: string;
  score_components: Record<string, number>;
}
