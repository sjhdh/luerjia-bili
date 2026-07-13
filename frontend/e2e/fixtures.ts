import type { ReportPayload } from "../src/types";

export const demoReport: ReportPayload = {
  id: "demo",
  keyword: "失控进化",
  generated_at: "2026-07-13T04:00:00Z",
  partial: false,
  warnings: [],
  hero: { cover_url: "https://i0.hdslb.com/bfs/archive/test.jpg", subtitle: "B站视频评论、可见弹幕与 TapTap 玩家评价联合分析" },
  metrics: { video_count: 30, selected_video_count: 10, comment_count: 980, danmaku_count: 466, review_count: 200, taptap_score: 8.4, overall_positive: 68.5, overall_neutral: 10.5, overall_negative: 21 },
  sentiment: {
    overall: { total: 1646, items: [{ name: "positive", label: "正面", count: 1127, percentage: 68.5 }, { name: "neutral", label: "中性", count: 173, percentage: 10.5 }, { name: "negative", label: "负面", count: 346, percentage: 21 }] },
    bilibili: { total: 1446, items: [{ name: "positive", label: "正面", count: 970, percentage: 67 }, { name: "neutral", label: "中性", count: 159, percentage: 11 }, { name: "negative", label: "负面", count: 317, percentage: 22 }] },
    taptap: { total: 200, items: [{ name: "positive", label: "正面", count: 140, percentage: 70 }, { name: "neutral", label: "中性", count: 18, percentage: 9 }, { name: "negative", label: "负面", count: 42, percentage: 21 }] }
  },
  rating_distribution: [{ star: 5, count: 117, percentage: 58.5 }, { star: 4, count: 23, percentage: 11.5 }, { star: 3, count: 17, percentage: 8.5 }, { star: 2, count: 12, percentage: 6 }, { star: 1, count: 31, percentage: 15.5 }],
  timeline: Array.from({ length: 12 }, (_, index) => ({ date: `2026-07-${String(index + 1).padStart(2, "0")}`, positive: 20 + index * 2, neutral: 5 + index % 3, negative: 8 + (index % 4), total: 40 + index * 3 })),
  keywords: ["优化", "玩法", "模式", "组队", "举报", "外挂", "画面", "操作", "建造", "资源", "发热", "掉帧", "公平", "单排", "氪金"].map((word, index) => ({ word, count: 120 - index * 6, negative_ratio: [3, 4, 5, 10, 11].includes(index) ? 0.68 : 0.24 })),
  tags: [{ name: "有趣好玩", count: 2000 }, { name: "运行稳定性", count: 846 }, { name: "外挂问题", count: 214 }, { name: "画面优秀", count: 153 }, { name: "玩法设计", count: 147 }, { name: "操作体验", count: 87 }],
  topics: [
    { id: 1, name: "非法组队 / 举报 / PVP", keywords: ["非法组队", "举报", "PVP"], size: 214, negative_ratio: 76, risk_score: 8.2, samples: ["举报无效"] },
    { id: 2, name: "外挂 / 公平 / 环境", keywords: ["外挂", "公平", "环境"], size: 126, negative_ratio: 69, risk_score: 6.8, samples: ["外挂影响体验"] },
    { id: 3, name: "优化 / 掉帧 / 发热", keywords: ["优化", "掉帧", "发热"], size: 98, negative_ratio: 61, risk_score: 5.9, samples: ["移动端发热"] }
  ],
  samples: {
    positive: [{ id: 1, platform: "taptap", kind: "review", source_scope: "taptap", author: "匿名用户 #A120", text: "建造手感很好，玩法深度足，和队友一起开荒很有意思。", rating: 5, likes: 82, confidence: 1 }],
    neutral: [{ id: 2, platform: "bilibili", kind: "comment", source_scope: "bilibili_discovery", author: "匿名用户 #B233", text: "玩法不错，但移动端优化还需要继续做，希望后续稳定一些。", rating: null, likes: 34, confidence: 0.78 }],
    negative: [{ id: 3, platform: "bilibili", kind: "comment", source_scope: "bilibili_discovery", author: "匿名用户 #C711", text: "非法组队举报后没有反馈，掉帧和发热也很明显。", rating: null, likes: 126, confidence: 0.93 }]
  },
  videos: Array.from({ length: 10 }, (_, index) => ({ id: `BVTEST${index}`, title: `失控进化重点视频 ${index + 1}：实机体验与版本评价`, url: "https://www.bilibili.com", cover_url: null, creator: `UP主 ${index + 1}`, published_at: `2026-07-${String(index + 1).padStart(2, "0")}T00:00:00Z`, views: 373000 - index * 17000, likes: 28000 - index * 900, coins: 5000 - index * 120, favorites: 8200 - index * 210, replies: 2400 - index * 80, danmakus: 6200 - index * 130, selection_score: 0.91 - index * 0.05, selected: true, source_scope: "bilibili_discovery", score_components: {} })),
  source_app: { id: "733908", title: "失控进化", url: "https://www.taptap.cn/app/733908", score: 8.4, rating_count: 11000 },
  model_quality: { sample_size: 200, accuracy: 0.835, macro_f1: 0.812, confusion: [[120, 10, 9], [4, 9, 4], [2, 4, 38]], model: "lxyuan/distilbert-base-multilingual-cased-sentiments-student", revision: "cf991100d706c13c0a080c097134c05b7f436c45" },
  summary: { overview: "整体口碑中上但存在明显两极分化，正面认可集中在玩法深度与建造体验。", positives: ["玩法深度", "建造体验", "公平感"], risks: ["非法组队与举报", "外挂", "移动端优化"], recommendations: ["优先改进举报反馈", "持续治理外挂", "优化移动端性能"] },
  methodology: { bilibili: "登录用户可见网页低频采集；评论 80%、可见弹幕 20% 加权", taptap: "公开网页评价；4-5星正面、3星中性、1-2星负面", combined: "平台等权平均；不使用隐藏 API，不绕过验证码或风控" }
};
