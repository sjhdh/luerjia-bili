import { BarChart3, Database, Home, LogOut, Settings } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import Dashboard from "./pages/Dashboard";
import JobDetail from "./pages/JobDetail";
import LoginPage from "./pages/LoginPage";
import type { AuthSession } from "./types";

const ReportPage = lazy(() => import("./pages/ReportPage"));

function AppShell({ onLogout }: { onLogout: () => void }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark"><BarChart3 size={19} /></span>
          <span>路尔嘉舆情分析</span>
        </Link>
        <nav className="nav-links" aria-label="主导航">
          <NavLink to="/" end><Home size={17} /><span>任务</span></NavLink>
          <span className="nav-disabled" title="数据保存在当前私有实例"><Database size={17} /><span>实例数据</span></span>
          <span className="nav-disabled" title="通过环境变量配置"><Settings size={17} /><span>设置</span></span>
          <button className="nav-logout" title="退出工作台" onClick={onLogout}><LogOut size={17} /><span>退出</span></button>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/jobs/:jobId" element={<JobDetail />} />
          <Route path="/reports/:jobId" element={<Suspense fallback={<div className="loading-page">加载报告</div>}><ReportPage /></Suspense>} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const shared = window.location.pathname.startsWith("/share/");
  const [session, setSession] = useState<AuthSession | null>(null);
  useEffect(() => {
    if (!shared) void api.authSession().then(setSession).catch(() => setSession({ authenticated: false, username: null }));
  }, [shared]);

  if (shared) {
    return <main className="shared-main"><Routes><Route path="/share/:shareToken" element={<Suspense fallback={<div className="loading-page">加载报告</div>}><ReportPage /></Suspense>} /></Routes></main>;
  }
  if (!session) return <div className="loading-page">验证会话</div>;
  if (!session.authenticated) return <LoginPage onSuccess={() => setSession({ authenticated: true, username: "operator" })} />;
  return <AppShell onLogout={() => void api.logout().finally(() => setSession({ authenticated: false, username: null }))} />;
}
