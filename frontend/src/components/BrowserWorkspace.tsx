import { ArrowLeft, ArrowRight, ExternalLink, LoaderCircle, RefreshCw, ShieldAlert, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { BrowserSession } from "../types";

interface Props {
  platform: BrowserSession["platform"];
  open: boolean;
  onClose: () => void;
  onSession?: (session: BrowserSession) => void;
}

export default function BrowserWorkspace({ platform, open, onClose, onSession }: Props) {
  const [frame, setFrame] = useState("");
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const viewport = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const lastMove = useRef(0);
  const inputQueue = useRef<Promise<void>>(Promise.resolve());

  const updateSession = useCallback((next: BrowserSession) => {
    setSession(next);
    onSession?.(next);
  }, [onSession]);

  const send = useCallback((payload: Record<string, unknown>) => {
    inputQueue.current = inputQueue.current
      .then(async () => updateSession(await api.browserInput(platform, payload)))
      .catch((err: Error) => setError(err.message));
    return inputQueue.current;
  }, [platform, updateSession]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    let objectUrl = "";
    setLoading(true);
    setError("");
    void api.openWorkspace(platform).then((next) => {
      if (active) updateSession(next);
    }).catch((err: Error) => active && setError(err.message));
    async function refreshFrame() {
      try {
        const response = await fetch(`/api/v1/platforms/${platform}/frame.jpg?t=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) throw new Error("页面画面暂不可用");
        const nextUrl = URL.createObjectURL(await response.blob());
        if (!active) { URL.revokeObjectURL(nextUrl); return; }
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = nextUrl;
        setFrame(nextUrl);
        setLoading(false);
      } catch (err) {
        if (active) setError((err as Error).message);
      }
    }
    void refreshFrame();
    const timer = window.setInterval(() => void refreshFrame(), 850);
    const stateTimer = window.setInterval(() => {
      void api.platformSession(platform).then((next) => active && updateSession(next)).catch(() => undefined);
    }, 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.clearInterval(stateTimer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [open, platform, updateSession]);

  if (!open) return null;

  function point(event: React.PointerEvent) {
    const rect = viewport.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
    };
  }

  return (
    <div className="browser-overlay" role="dialog" aria-modal="true" aria-label={`${platform} 页面子窗口`}>
      <section className="browser-window">
        <header className="browser-toolbar">
          <div className="browser-nav">
            <button className="icon-button" title="后退" onClick={() => void send({ type: "back" })}><ArrowLeft size={17} /></button>
            <button className="icon-button" title="前进" onClick={() => void send({ type: "forward" })}><ArrowRight size={17} /></button>
            <button className="icon-button" title="刷新" onClick={() => void send({ type: "reload" })}><RefreshCw size={17} /></button>
          </div>
          <div className="browser-address"><span className={`source-dot source-${platform}`} /> <span>{session?.page_title || (platform === "bilibili" ? "B站" : "TapTap")}</span><small>{session?.current_url || "正在连接"}</small></div>
          <div className="browser-status">{session?.risk_detected && <ShieldAlert size={16} />}<span>{session?.authenticated ? "已登录" : "未登录"}</span></div>
          {session?.current_url && <a className="icon-button" href={session.current_url} target="_blank" rel="noreferrer" title="在新标签页打开"><ExternalLink size={17} /></a>}
          <button className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button>
        </header>
        {error && <div className="browser-error">{error}</div>}
        <div
          className="browser-viewport"
          ref={viewport}
          tabIndex={0}
          onPointerDown={(event) => {
            dragging.current = true;
            event.currentTarget.setPointerCapture(event.pointerId);
            void send({ type: "pointer", action: "down", ...point(event) });
          }}
          onPointerMove={(event) => {
            if (!dragging.current || Date.now() - lastMove.current < 45) return;
            lastMove.current = Date.now();
            void send({ type: "pointer", action: "move", ...point(event) });
          }}
          onPointerUp={(event) => {
            dragging.current = false;
            void send({ type: "pointer", action: "up", ...point(event) });
          }}
          onWheel={(event) => { event.preventDefault(); void send({ type: "wheel", delta_y: event.deltaY }); }}
          onKeyDown={(event) => {
            if (event.ctrlKey || event.metaKey || event.altKey) return;
            event.preventDefault();
            void send(event.key.length === 1 ? { type: "text", text: event.key } : { type: "key", key: event.key });
          }}
          onPaste={(event) => {
            event.preventDefault();
            void send({ type: "text", text: event.clipboardData.getData("text").slice(0, 500) });
          }}
        >
          {frame && <img src={frame} alt={`${platform} 交互页面`} draggable={false} />}
          {loading && <div className="browser-loading"><LoaderCircle className="spin" size={22} />加载页面</div>}
        </div>
      </section>
    </div>
  );
}
