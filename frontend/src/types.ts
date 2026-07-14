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

export type AnalysisMode = "local" | "lightweight" | "full";

export interface Job {
  id: string;
  keyword: string;
  status: JobStatus;
  stage: string;
  progress: number;
  message: string;
  analysis_mode: AnalysisMode;
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

export type ProxyMode = "direct" | "manual" | "auto";
export type ProxyProtocol = "http" | "https" | "socks4" | "socks5";
export type ProxyPoolProvider = "smart" | "scdn" | "zdopen";
export type ProxyPlatformScope = "taptap" | "all";

export interface ProxySettings {
  mode: ProxyMode;
  protocol: ProxyProtocol;
  country_code: string;
  pool_size: number;
  pool_provider: ProxyPoolProvider;
  platform_scope: ProxyPlatformScope;
  allow_tls_interception: boolean;
  auto_rotate_on_risk: boolean;
  risk_rotation_limit: number;
  zdopen_app_id: string;
  zdopen_configured: boolean;
  manual_proxy: string;
  active_proxy: string | null;
  active_source: "direct" | "manual" | "pool";
  exit_ip: string | null;
  latency_ms: number | null;
  last_checked_at: string | null;
  last_error: string | null;
  target_results: Record<string, boolean>;
  active_provider: string | null;
  tls_intercepted: boolean;
  pool_api: string;
  pool_apis: Record<string, string>;
}

export interface ProxyCheck {
  proxy: string;
  reachable: boolean;
  latency_ms: number | null;
  exit_ip: string | null;
  message: string;
  checked_at: string;
  targets: Record<string, boolean>;
  provider: string | null;
  tls_intercepted: boolean;
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
  estimated?: boolean;
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
    id: string | number;
    name: string;
    keywords: string[];
    size: number;
    negative_ratio: number;
    risk_score: number;
    samples: string[];
    weighted_negative?: number;
  }>;
  analysis?: {
    mode: AnalysisMode;
    sentiment_source: string;
    llm_model?: string;
    prompt_version?: string;
    llm_coverage?: number;
    llm_covered_count?: number;
    llm_routed_count?: number;
    llm_route_ratio?: number;
    llm_row_route_ratio?: number;
    llm_success_rate?: number;
    llm_route_reasons?: Record<string, number>;
    llm_calibration_unique_count?: number;
    llm_targeted_unique_count?: number;
    llm_total_unique_input_count?: number;
    sentiment_estimation?: string;
    sentiment_calibration_sample_size?: number;
    llm_unique_input_count?: number;
    llm_batch_count?: number;
    local_llm_agreement?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    report_generated?: boolean;
  };
  ai_analysis?: {
    executive_summary: string;
    findings: Array<{ title: string; detail: string; evidence_ids?: number[] }>;
    risks: Array<{ title: string; detail: string; evidence_ids?: number[] }>;
    actions: Array<{ priority: "P0" | "P1" | "P2"; title: string; rationale: string; action: string }>;
    caveats: string[];
    evidence?: Array<{
      id: number;
      text: string;
      sentiment: string;
      confidence: number | null;
      likes: number;
      source_scope: string;
      topics: string[];
    }>;
    model: string;
    prompt_version: string;
  } | null;
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
    sentiment_source?: string;
    llm_coverage?: number;
    llm_covered_count?: number;
    local_llm_agreement?: number;
    prompt_version?: string;
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
