import { Activity, CheckCircle2, ExternalLink, Globe2, LoaderCircle, RefreshCw, Route, Save, ShieldAlert, Timer, Unplug } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ProxyCheck, ProxyMode, ProxyProtocol, ProxySettings } from "../types";

const defaults: ProxySettings = {
  mode: "direct",
  protocol: "https",
  country_code: "CN",
  pool_size: 5,
  manual_proxy: "",
  active_proxy: null,
  active_source: "direct",
  exit_ip: null,
  latency_ms: null,
  last_checked_at: null,
  last_error: null,
  pool_api: "https://proxy.scdn.io/api/get_proxy.php"
};

const modeLabel: Record<ProxyMode, string> = { direct: "直连", manual: "手动代理", auto: "自动代理池" };

export default function ProxySettingsPage() {
  const [settings, setSettings] = useState<ProxySettings>(defaults);
  const [mode, setMode] = useState<ProxyMode>("direct");
  const [protocol, setProtocol] = useState<ProxyProtocol>("https");
  const [countryCode, setCountryCode] = useState("CN");
  const [poolSize, setPoolSize] = useState(5);
  const [manualProxy, setManualProxy] = useState("");
  const [check, setCheck] = useState<ProxyCheck | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | "rotate" | "">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const applyState = useCallback((next: ProxySettings) => {
    setSettings(next);
    setMode(next.mode);
    setProtocol(next.protocol);
    setCountryCode(next.country_code);
    setPoolSize(next.pool_size);
    setManualProxy(next.manual_proxy);
  }, []);

  useEffect(() => {
    void api.proxySettings().then(applyState).catch((err: Error) => setError(err.message));
  }, [applyState]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy("save"); setError(""); setNotice(""); setCheck(null);
    try {
      const next = await api.updateProxy({ mode, protocol, country_code: countryCode, pool_size: poolSize, manual_proxy: manualProxy });
      applyState(next);
      setNotice(`${modeLabel[next.mode]}已生效，平台页面将在下次打开时使用新线路`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function testRoute() {
    setBusy("test"); setError(""); setNotice("");
    try {
      const candidate = mode === "manual" ? manualProxy : settings.active_proxy;
      const result = await api.testProxy(candidate || null, protocol);
      setCheck(result);
      setNotice(result.message);
      setSettings((current) => ({ ...current, exit_ip: result.exit_ip, latency_ms: result.latency_ms, last_checked_at: result.checked_at, last_error: result.reachable ? null : result.message }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function rotate() {
    setBusy("rotate"); setError(""); setNotice(""); setCheck(null);
    try {
      const next = await api.rotateProxy();
      applyState(next);
      setNotice("已从代理池切换到新的可用线路");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  const routeHealthy = settings.mode === "direct" || Boolean(settings.active_proxy && !settings.last_error);

  return <div className="workspace settings-workspace">
    <header className="settings-header">
      <div><p className="eyebrow">NETWORK ROUTE</p><h1>网络路由</h1><p className="workspace-lede">管理平台浏览器使用的出口线路</p></div>
      <span className={`route-health ${routeHealthy ? "healthy" : "warning"}`}>{routeHealthy ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}{routeHealthy ? "线路可用" : "需要处理"}</span>
    </header>

    {error && <div className="alert error-alert">{error}</div>}
    {notice && <div className="alert success-alert">{notice}</div>}

    <section className="route-console" aria-label="当前网络线路">
      <div className="route-console-title"><span><Route size={19} /></span><div><small>当前线路</small><strong>{modeLabel[settings.mode]}</strong></div></div>
      <div className="route-stat"><Globe2 size={16} /><span>出口</span><strong>{settings.exit_ip || (settings.mode === "direct" ? "服务器直连" : "待检测")}</strong></div>
      <div className="route-stat"><Timer size={16} /><span>延迟</span><strong>{settings.latency_ms != null ? `${settings.latency_ms} ms` : "--"}</strong></div>
      <div className="route-stat route-endpoint"><Activity size={16} /><span>节点</span><strong>{settings.active_proxy || "DIRECT"}</strong></div>
    </section>

    <section className="proxy-tool">
      <div className="section-heading"><div><h2>线路策略</h2><span>切换会重建平台页面，但不会清除登录资料</span></div></div>
      <form className="proxy-form" onSubmit={save}>
        <fieldset className="field mode-field proxy-mode"><legend>使用方式</legend><div className="segmented three-way">
          {(["direct", "manual", "auto"] as ProxyMode[]).map((value) => <button type="button" key={value} className={mode === value ? "active" : ""} onClick={() => setMode(value)}>{modeLabel[value]}</button>)}
        </div></fieldset>

        {mode !== "direct" && <div className="proxy-options">
          <label className="field"><span>协议</span><select value={protocol} onChange={(event) => setProtocol(event.target.value as ProxyProtocol)}><option value="https">HTTPS</option><option value="http">HTTP</option><option value="socks5">SOCKS5</option><option value="socks4">SOCKS4</option></select></label>
          {mode === "manual" ? <label className="field proxy-address"><span>代理地址</span><input value={manualProxy} onChange={(event) => setManualProxy(event.target.value)} placeholder="IP:端口" required /></label> : <>
            <label className="field"><span>国家代码</span><input value={countryCode} maxLength={2} onChange={(event) => setCountryCode(event.target.value.toUpperCase())} placeholder="CN" /></label>
            <label className="field"><span>候选数量</span><input type="number" min={1} max={20} value={poolSize} onChange={(event) => setPoolSize(Number(event.target.value))} /></label>
          </>}
        </div>}

        <div className="proxy-actions">
          <button className="button primary" disabled={Boolean(busy)}>{busy === "save" ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}保存并切换</button>
          {mode !== "direct" && <button type="button" className="button secondary" disabled={Boolean(busy) || (mode === "manual" && !manualProxy.trim())} onClick={() => void testRoute()}>{busy === "test" ? <LoaderCircle className="spin" size={17} /> : <Activity size={17} />}检测线路</button>}
          {settings.mode === "auto" && <button type="button" className="button secondary" disabled={Boolean(busy)} onClick={() => void rotate()}>{busy === "rotate" ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}换一个节点</button>}
        </div>
      </form>

      {check && <div className={`proxy-check ${check.reachable ? "reachable" : "unreachable"}`}>{check.reachable ? <CheckCircle2 size={18} /> : <Unplug size={18} />}<div><strong>{check.message}</strong><span>{check.proxy}{check.exit_ip ? ` · 出口 ${check.exit_ip}` : ""}{check.latency_ms != null ? ` · ${check.latency_ms} ms` : ""}</span></div></div>}
      <footer className="proxy-source"><span>代理池来源</span><a href={settings.pool_api} target="_blank" rel="noreferrer">proxy.scdn.io <ExternalLink size={13} /></a></footer>
    </section>
  </div>;
}
