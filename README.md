# 路尔嘉舆情分析

面向单一操作者的 B站 + TapTap 舆情分析工具。它通过用户可见网页低频采集视频、评论、弹幕列表和 TapTap 评价，完成情感分类、主题聚类、风险排序与报告导出。既可在 Windows 本机运行，也可作为受保护的 Linux 私有服务部署。

## 边界

- 应用进程始终只绑定 `127.0.0.1`；服务器模式通过 nginx HTTPS 反向代理，并强制使用共享访问口令。
- B站 Cookie 只存在于浏览器配置目录中，不进入数据库、日志、API 或导出文件。服务器目录仅允许专用系统用户读取。
- 只读取登录用户能够看到的网页内容，不调用隐藏接口，不绕过验证码、WBI 或风控。
- 页面出现验证码、`-352` 或结构无法识别时，任务暂停并等待人工处理。

## 环境

- Windows 10/11 或带 systemd 的 Linux 服务器
- Python 3.11+
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

## Linux 私有部署

服务器模式使用无头 Chromium 打开 B站官方登录页，将页面上的二维码作为短时 PNG 返回给工作台。操作者使用哔哩哔哩客户端扫码确认，登录 Cookie 只保存在服务器的 `/var/lib/autobili/data/browser-profile/`。

推荐目录：

- 程序：`/opt/autobili`
- 数据、模型与浏览器：`/var/lib/autobili`
- 私密配置：`/etc/autobili.env`
- 服务：`autobili.service`

在服务器取得代码并构建前端后：

```bash
sudo install -o root -g root -m 0755 -d /opt/autobili
sudo bash deploy/install.sh
```

首次安装会生成并显示一次独立的随机访问口令，同时以 `root:autobili 0640` 保存到 `/etc/autobili.env`。`DEPLOYMENT_MODE=server` 时 `ADMIN_PASSWORD` 不能为空，应用会拒绝在没有访问口令的情况下启动。需要改口令时编辑 `/etc/autobili.env` 并重启 `autobili.service`。

标准 nginx 配置位于 `deploy/nginx-autobili.conf`，脚本同时识别 `/etc/nginx` 和宝塔 `/www/server/panel/vhost/nginx`。确认 `autobili.luerjia.art` 已解析到服务器且 HTTP 可访问后，可用独立 Certbot 环境在不提供邮箱的情况下申请证书并安装自动续期 timer：

```bash
sudo bash deploy/enable-https.sh
```

现有 nginx 使用宝塔等自定义目录时，只需把同一虚拟主机内容加入其站点配置，不应覆盖其他域名配置。SSE 路径必须保持 `proxy_buffering off`。

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
