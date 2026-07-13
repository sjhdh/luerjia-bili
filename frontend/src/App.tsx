import { BarChart3, Database, Home, Settings } from "lucide-react";
import { lazy, Suspense } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import JobDetail from "./pages/JobDetail";

const ReportPage = lazy(() => import("./pages/ReportPage"));

function AppShell() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark"><BarChart3 size={19} /></span>
          <span>路尔嘉舆情分析</span>
        </Link>
        <nav className="nav-links" aria-label="主导航">
          <NavLink to="/" end><Home size={17} /><span>任务</span></NavLink>
          <span className="nav-disabled" title="数据保存在本机"><Database size={17} /><span>本地数据</span></span>
          <span className="nav-disabled" title="通过环境变量配置"><Settings size={17} /><span>设置</span></span>
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
  return <AppShell />;
}
