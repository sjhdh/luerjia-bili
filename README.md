# 路尔嘉舆情分析

本机运行的 B站 + TapTap 舆情分析工具。它通过用户可见网页低频采集视频、评论、弹幕列表和 TapTap 评价，在本机完成情感分类、主题聚类、风险排序与报告导出。

## 边界

- 服务仅绑定 `127.0.0.1`，没有用户系统或公网分享。
- B站 Cookie 只存在于 `data/browser-profile/` 的 Chromium 配置中，不进入数据库、日志、API 或导出文件。
- 只读取登录用户能够看到的网页内容，不调用隐藏接口，不绕过验证码、WBI 或风控。
- 页面出现验证码、`-352` 或结构无法识别时，任务暂停并等待人工处理。

## 环境

- Windows 10/11
- Python 3.12+
- Node.js 22+
- 首次安装和首次下载本地模型时需要网络

## 安装与启动

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\scripts\start.ps1
```

启动后访问 [http://127.0.0.1:8000](http://127.0.0.1:8000)。点击“连接 B站”会打开独立 Chromium 窗口，登录完成后即可创建任务。

开发模式：

```powershell
.\scripts\dev.ps1
```

前端运行在 `http://127.0.0.1:5173`，API 仍在 `http://127.0.0.1:8000`。

## 分析口径

- 标准任务：30 个候选视频、10 个重点视频、最多 1000 条评论、500 条页面可见弹幕、200 条 TapTap 评价。
- 视频权重：相关度 32%、播放量 24%、评论量 12%、弹幕量 8%、点赞率 8%、投币率 6%、收藏率 5%、时效 5%。
- TapTap 星级：4–5 星正面、3 星中性、1–2 星负面。
- 本地模型：`lxyuan/distilbert-base-multilingual-cased-sentiments-student`，固定 revision `cf991100d706c13c0a080c097134c05b7f436c45`。
- B站情感：评论占 80%，弹幕占 20%；跨平台指标采用平台等权。

## 可选 LLM 增强

复制 `.env.example` 为 `.env.local` 并设置：

```dotenv
OPENAI_BASE_URL=https://example.com/v1
OPENAI_API_KEY=...
OPENAI_MODEL=...
```

增强模式只发送经过邮箱、手机号、QQ、URL 和用户名脱敏的代表性片段。接口失败会自动退回本地总结。

## 数据

- SQLite：`data/luerjia.db`
- B站浏览器资料：`data/browser-profile/`
- 默认原文保留 30 天，报告保留 180 天。
- UI 可清除 B站浏览器资料；删除 `data/` 可重置全部本地状态。

## 验证

```powershell
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m mypy backend/app --no-incremental
.\.venv\Scripts\python.exe -m pytest -q

Push-Location frontend
npm run lint
npm run test
npm run build
npm run e2e
Pop-Location
```

CI 和自动化测试只使用保存的 HTML 与 API mock，不访问真实平台，也不需要 Cookie。
