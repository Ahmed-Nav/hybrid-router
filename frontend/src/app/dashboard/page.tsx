"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "https://ahmednav-hybrid-router.hf.space";

interface UserInfo {
  username: string;
  role: string;
  tenant_id: string | null;
}

interface UsageLogItem {
  timestamp: string;
  model_used: string;
  billed_usage_cost: number;
  prompt_tokens: number;
  completion_tokens: number;
  used_fallback: boolean;
}

interface Metrics {
  tenant_id: string;
  plan_tier: string;
  routing_mode: string;
  fallback_provider: string;
  base_fee: number;
  total_spend: number;
  total_reference_cost: number;
  total_tokens: number;
  total_requests: number;
  fallback_count: number;
  monthly_budget_cap: number | null;
  recent_logs: UsageLogItem[];
  api_key_hash: string;
}

interface TimeseriesDay {
  date: string;
  billed_usage_cost: number;
  reference_cost: number;
  request_count: number;
  fallback_count: number;
}

interface AdminOverview {
  total_tenant_count: number;
  active_tenant_count: number;
  total_revenue: number;
  total_cogs: number;
  platform_profit: number;
  total_reference_cost_saved: number;
  fallback_trigger_count: number;
}

interface AdminTenantRow {
  tenant_id: string;
  plan_tier: string;
  is_active: boolean;
  revenue_this_period: number;
  cogs_this_period: number;
  profit_this_period: number;
  last_active: string | null;
  monthly_budget_cap: number | null;
  churn_risk: boolean;
  tier_capped_count: number;
}

interface AdminTimeseriesDay {
  date: string;
  request_count: number;
  fallback_count: number;
}

const PLAN_BASE_FEES: Record<string, number> = { BASIC: 1999.0, PREMIUM: 6999.0 };

function SpendTrendChart({ data }: { data: TimeseriesDay[] }) {
  if (data.length === 0) return null;
  const width = 600;
  const height = 160;
  const barGap = 2;
  const barWidth = width / data.length - barGap;
  const maxValue = Math.max(...data.map((d) => Math.max(d.billed_usage_cost, d.reference_cost)), 0.0001);

  return (
    <svg viewBox={`0 0 ${width} ${height + 20}`} className="w-full h-40" preserveAspectRatio="none">
      {data.map((d, i) => {
        const x = i * (barWidth + barGap);
        const refHeight = (d.reference_cost / maxValue) * height;
        const billedHeight = (d.billed_usage_cost / maxValue) * height;
        return (
          <g key={d.date}>
            <rect x={x} y={height - refHeight} width={barWidth} height={refHeight} fill="#E5E1D8" />
            <rect x={x} y={height - billedHeight} width={barWidth} height={billedHeight} fill="#F28C28" />
          </g>
        );
      })}
      <line x1={0} y1={height} x2={width} y2={height} stroke="#1E1E1E" strokeWidth={1} />
    </svg>
  );
}

function RequestVolumeChart({ data }: { data: AdminTimeseriesDay[] }) {
  if (data.length === 0) return null;
  const width = 600;
  const height = 160;
  const barGap = 2;
  const barWidth = width / data.length - barGap;
  const maxValue = Math.max(...data.map((d) => d.request_count), 1);

  return (
    <svg viewBox={`0 0 ${width} ${height + 20}`} className="w-full h-40" preserveAspectRatio="none">
      {data.map((d, i) => {
        const x = i * (barWidth + barGap);
        const totalHeight = (d.request_count / maxValue) * height;
        const fallbackHeight = (d.fallback_count / maxValue) * height;
        return (
          <g key={d.date}>
            <rect x={x} y={height - totalHeight} width={barWidth} height={totalHeight} fill="#E5E1D8" />
            <rect x={x} y={height - fallbackHeight} width={barWidth} height={fallbackHeight} fill="#ef4444" />
          </g>
        );
      })}
      <line x1={0} y1={height} x2={width} y2={height} stroke="#1E1E1E" strokeWidth={1} />
    </svg>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [adminOverview, setAdminOverview] = useState<AdminOverview | null>(null);
  const [adminTenants, setAdminTenants] = useState<AdminTenantRow[]>([]);
  const [adminTimeseries, setAdminTimeseries] = useState<AdminTimeseriesDay[]>([]);
  const [timeseries, setTimeseries] = useState<TimeseriesDay[]>([]);
  const [activeTab, setActiveTab] = useState("");
  const [loading, setLoading] = useState(true);

  // Routing preference state — initialised from the analytics response
  const [routingMode, setRoutingMode] = useState("SMART");
  const [fallbackProvider, setFallbackProvider] = useState("groq");
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsMsg, setSettingsMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Budget cap state
  const [budgetCapInput, setBudgetCapInput] = useState("");
  const [budgetCapSaving, setBudgetCapSaving] = useState(false);
  const [budgetCapMsg, setBudgetCapMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // API key rotation state
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [rotating, setRotating] = useState(false);
  const [rotateMsg, setRotateMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Password change state
  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [pwdSaving, setPwdSaving] = useState(false);
  const [pwdMsg, setPwdMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const storedToken = localStorage.getItem("auth_token");
    const storedUser = localStorage.getItem("user_info");

    if (!storedToken || !storedUser) {
      router.push("/login");
      return;
    }

    setToken(storedToken);
    const parsedUser = JSON.parse(storedUser) as UserInfo;
    setUser(parsedUser);
    setActiveTab(parsedUser.role === "SUPER_ADMIN" ? "Platform Overview" : "Overview");

    if (parsedUser.role === "SUPER_ADMIN") {
      fetchAdminData(storedToken);
    } else {
      fetchMetrics(storedToken);
    }
  }, [router]);

  const fetchMetrics = async (authToken: string) => {
    try {
      const [analyticsRes, timeseriesRes] = await Promise.all([
        fetch(`${BACKEND_URL}/v1/analytics`, { headers: { Authorization: `Bearer ${authToken}` } }),
        fetch(`${BACKEND_URL}/v1/analytics/timeseries?days=30`, { headers: { Authorization: `Bearer ${authToken}` } }),
      ]);
      if (analyticsRes.ok) {
        const data = await analyticsRes.json();
        setMetrics(data);
        if (data.routing_mode) setRoutingMode(data.routing_mode);
        if (data.fallback_provider) setFallbackProvider(data.fallback_provider);
        setBudgetCapInput(data.monthly_budget_cap != null ? String(data.monthly_budget_cap) : "");
      } else {
        console.error("Failed to load metrics from API gateway");
      }
      if (timeseriesRes.ok) {
        const tsData = await timeseriesRes.json();
        setTimeseries(tsData.daily);
      }
    } catch (err) {
      console.error("API gateway connection error:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchAdminData = async (authToken: string) => {
    try {
      const [overviewRes, tenantsRes, timeseriesRes] = await Promise.all([
        fetch(`${BACKEND_URL}/v1/admin/overview`, { headers: { Authorization: `Bearer ${authToken}` } }),
        fetch(`${BACKEND_URL}/v1/admin/tenants`, { headers: { Authorization: `Bearer ${authToken}` } }),
        fetch(`${BACKEND_URL}/v1/admin/timeseries?days=30`, { headers: { Authorization: `Bearer ${authToken}` } }),
      ]);
      if (overviewRes.ok) setAdminOverview(await overviewRes.json());
      if (tenantsRes.ok) setAdminTenants((await tenantsRes.json()).tenants);
      if (timeseriesRes.ok) setAdminTimeseries((await timeseriesRes.json()).daily);
    } catch (err) {
      console.error("Admin data connection error:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("user_info");
    router.push("/login");
  };

  const handleRotateKey = async () => {
    setRotating(true);
    setRotateMsg(null);
    try {
      const res = await fetch(`${BACKEND_URL}/v1/tenant/api-key/rotate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setRevealedKey(data.api_key);
        setRotateMsg({ ok: true, text: "New key generated. Copy it now — it will not be shown again." });
        if (token) fetchMetrics(token);
      } else {
        const err = await res.json().catch(() => ({}));
        setRotateMsg({ ok: false, text: err.detail || "Failed to generate a new key." });
      }
    } catch {
      setRotateMsg({ ok: false, text: "Connection error. Please try again." });
    } finally {
      setRotating(false);
    }
  };

  if (loading || !user) {
    return (
      <div className="min-h-screen bg-[#F5F4F0] flex justify-center items-center font-mono">
        Loading your dashboard...
      </div>
    );
  }

  const getTabs = () => {
    if (user.role === "SUPER_ADMIN") {
      return ["Platform Overview", "Tenants", "Infrastructure", "Security Settings"];
    } else if (user.role === "TENANT_ADMIN") {
      return ["Overview", "Billing", "Routing", "API Keys", "Security Settings"];
    } else {
      return ["Overview", "API Key", "Docs & Code Samples", "Usage", "Security Settings"];
    }
  };

  const tabs = getTabs();
  const baseFee = metrics?.base_fee ?? PLAN_BASE_FEES[metrics?.plan_tier || "BASIC"] ?? 0;
  const usageThisMonth = metrics?.total_spend || 0;
  const totalBill = baseFee + usageThisMonth;
  const savings = Math.max(0, (metrics?.total_reference_cost || 0) - usageThisMonth);

  // Simple mean-daily-rate forecast from the last 30 days of usage, projected across the current month.
  const daysInThisMonth = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate();
  const recentDailyTotal = timeseries.reduce((sum, d) => sum + d.billed_usage_cost, 0);
  const recentDaySpan = timeseries.length || 1;
  const meanDailyRate = recentDailyTotal / recentDaySpan;
  const forecastedMonthTotal = baseFee + meanDailyRate * daysInThisMonth;

  const budgetCap = metrics?.monthly_budget_cap ?? null;
  const budgetUsedPct = budgetCap && budgetCap > 0 ? (usageThisMonth / budgetCap) * 100 : null;

  return (
    <div className="min-h-screen bg-[#F5F4F0] text-[#1E1E1E] flex flex-col md:flex-row font-sans">

      {/* Sidebar Navigation Layout */}
      <aside className="w-full md:w-64 bg-white border-b-4 md:border-b-0 md:border-r-4 border-[#1E1E1E] p-6 flex flex-col justify-between">
        <div>
          <div className="mb-6 pb-4 border-b-2 border-gray-100">
            <h2 className="text-xl font-extrabold tracking-tight font-mono text-[#F28C28]">Hybrid Router</h2>
            <div className="mt-2 text-xs text-gray-500">
              <p>Tenant: <strong className="text-[#1E1E1E]">{user.tenant_id || "All Tenants"}</strong></p>
              <p>Role: <strong className="text-[#1E1E1E]">{user.role}</strong></p>
            </div>
          </div>

          <nav className="space-y-2">
            {tabs.map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`w-full text-left px-3 py-2 border-2 font-bold transition duration-100 ${
                  activeTab === tab
                    ? "bg-[#F28C28] text-white border-[#1E1E1E] shadow-[2px_2px_0px_#1E1E1E]"
                    : "border-transparent hover:border-[#1E1E1E] hover:bg-gray-50"
                }`}
              >
                {tab}
              </button>
            ))}
          </nav>
        </div>

        <button
          onClick={handleLogout}
          className="mt-8 w-full bg-red-50 text-red-700 border-2 border-red-700 py-2 font-bold hover:bg-red-700 hover:text-white transition duration-150 shadow-[2px_2px_0px_#1E1E1E]"
        >
          Log Out
        </button>
      </aside>

      {/* Main content viewport */}
      <main className="flex-1 p-8">
        <h2 className="text-3xl font-extrabold mb-6 font-mono border-b-4 border-[#1E1E1E] pb-2">
          {activeTab}
        </h2>

        {/* -------------------- TENANT-FACING OVERVIEW -------------------- */}
        {activeTab === "Overview" && (
          <div className="space-y-6 max-w-3xl">
            {budgetUsedPct !== null && budgetUsedPct >= 80 && (
              <div className={`border-4 p-4 shadow-[6px_6px_0px_#7f1d1d] ${budgetUsedPct >= 100 ? "bg-red-50 border-red-600" : "bg-orange-50 border-orange-500"}`}>
                <p className={`text-sm font-bold ${budgetUsedPct >= 100 ? "text-red-700" : "text-orange-700"}`}>
                  {budgetUsedPct >= 100
                    ? `You've exceeded your monthly budget cap of ₹${budgetCap?.toFixed(2)}.`
                    : `You've used ${budgetUsedPct.toFixed(0)}% of your monthly budget cap of ₹${budgetCap?.toFixed(2)}.`}
                </p>
              </div>
            )}
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Your Bill This Month</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Base Plan ({metrics?.plan_tier || "BASIC"})</p>
                  <h2 className="text-2xl font-extrabold">₹{baseFee.toFixed(2)}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Usage This Month</p>
                  <h2 className="text-2xl font-extrabold">₹{usageThisMonth.toFixed(4)}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Total</p>
                  <h2 className="text-2xl font-extrabold text-[#F28C28]">₹{totalBill.toFixed(2)}</h2>
                </div>
              </div>
            </div>

            <div className="bg-[#FFFDF9] border-4 border-[#F28C28] p-6 shadow-[6px_6px_0px_#F28C28]">
              <h3 className="text-xl font-bold text-[#F28C28] mb-2 font-mono">You Saved ₹{savings.toFixed(4)} This Month</h3>
              <p className="text-sm text-gray-600">
                Savings = what you would have paid if every request had used a top-tier premium model directly, compared to what we actually billed you.
              </p>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-lg font-bold mb-2 font-mono">Reliability</h3>
              <p className="text-sm text-gray-700">
                {metrics?.fallback_count ?? 0} request{(metrics?.fallback_count ?? 0) === 1 ? "" : "s"} automatically failed over to your backup provider
                ({metrics?.fallback_provider || "groq"}) — zero downtime for you.
              </p>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-lg font-bold mb-2 font-mono">Current Routing Mode: {metrics?.routing_mode || "SMART"}</h3>
              <p className="text-sm text-gray-700">
                {metrics?.routing_mode === "ECO" && "Maximizing cost efficiency — requests are kept on cheaper models whenever possible."}
                {metrics?.routing_mode === "PERFORMANCE" && "Maximizing quality — complex requests always reach the top-tier model."}
                {(!metrics?.routing_mode || metrics?.routing_mode === "SMART") && "Balancing cost and quality automatically per request."}
              </p>
            </div>
          </div>
        )}

        {/* -------------------- TENANT ADMIN: BILLING -------------------- */}
        {activeTab === "Billing" && (
          <div className="space-y-6">
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Spend Summary</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Usage This Month</p>
                  <h2 className="text-3xl font-extrabold text-[#F28C28]">₹{usageThisMonth.toFixed(4)}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Total Tokens Processed</p>
                  <h2 className="text-3xl font-extrabold text-[#F28C28]">{metrics?.total_tokens.toLocaleString() || "0"}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Account Tier</p>
                  <h2 className="text-3xl font-extrabold text-[#F28C28]">{metrics?.plan_tier || "BASIC"}</h2>
                </div>
              </div>
            </div>

            <div className="bg-[#FFFDF9] border-4 border-[#F28C28] p-6 shadow-[6px_6px_0px_#F28C28]">
              <h3 className="text-xl font-bold text-[#F28C28] mb-2 font-mono">Savings vs. Calling Premium Models Directly</h3>
              <p className="text-sm text-gray-600 mb-4">The router keeps simple requests off expensive top-tier models automatically.</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase">Reference Cost (going direct)</p>
                  <h2 className="text-2xl font-bold">₹{(metrics?.total_reference_cost || 0).toFixed(4)}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase text-[#F28C28]">You Saved</p>
                  <h2 className="text-2xl font-extrabold text-[#F28C28]">₹{savings.toFixed(4)}</h2>
                </div>
              </div>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-1 font-mono">30-Day Spend Trend</h3>
              <p className="text-xs text-gray-500 mb-4">
                <span className="inline-block w-3 h-3 bg-[#F28C28] mr-1 align-middle"></span> Billed to you
                <span className="inline-block w-3 h-3 bg-[#E5E1D8] ml-4 mr-1 align-middle"></span> Reference cost (going direct)
              </p>
              {timeseries.length === 0 ? (
                <div className="bg-gray-50 p-4 border-2 border-dashed border-gray-300 text-center text-gray-500 text-sm">
                  Not enough usage yet to show a trend.
                </div>
              ) : (
                <SpendTrendChart data={timeseries} />
              )}
              <p className="text-sm text-gray-700 mt-4">
                At this rate, you're projected to spend about <strong>₹{forecastedMonthTotal.toFixed(2)}</strong> by the end of this month (base plan + usage).
              </p>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E] max-w-md">
              <h3 className="text-xl font-bold mb-2 font-mono">Monthly Budget Cap</h3>
              <p className="text-sm text-gray-600 mb-4">Set a spending alert threshold — we'll warn you as your usage approaches it. This does not block requests.</p>
              {budgetCap && budgetUsedPct !== null && (
                <div className="mb-4">
                  <div className="h-3 bg-gray-100 border-2 border-[#1E1E1E] overflow-hidden">
                    <div
                      className={`h-full ${budgetUsedPct >= 100 ? "bg-red-600" : budgetUsedPct >= 80 ? "bg-orange-500" : "bg-green-600"}`}
                      style={{ width: `${Math.min(100, budgetUsedPct)}%` }}
                    />
                  </div>
                  <p className="text-xs text-gray-500 mt-1">₹{usageThisMonth.toFixed(2)} of ₹{budgetCap.toFixed(2)} used ({budgetUsedPct.toFixed(0)}%)</p>
                </div>
              )}
              {budgetCapMsg && (
                <div className={`p-3 border-2 text-sm font-semibold mb-4 ${budgetCapMsg.ok ? "bg-green-50 border-green-500 text-green-700" : "bg-red-50 border-red-500 text-red-700"}`}>
                  {budgetCapMsg.ok ? "✓" : "⚠️"} {budgetCapMsg.text}
                </div>
              )}
              <div className="flex gap-2">
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={budgetCapInput}
                  onChange={(e) => setBudgetCapInput(e.target.value)}
                  placeholder="e.g. 5000"
                  className="flex-1 p-2.5 border-2 border-[#1E1E1E] outline-none focus:border-[#F28C28]"
                />
                <button
                  disabled={budgetCapSaving}
                  onClick={async () => {
                    setBudgetCapSaving(true);
                    setBudgetCapMsg(null);
                    try {
                      const parsed = budgetCapInput === "" ? null : parseFloat(budgetCapInput);
                      const res = await fetch(`${BACKEND_URL}/v1/tenant/settings`, {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                        body: JSON.stringify({ monthly_budget_cap: parsed }),
                      });
                      if (res.ok) {
                        setBudgetCapMsg({ ok: true, text: "Budget cap saved." });
                        if (token) fetchMetrics(token);
                      } else {
                        const err = await res.json().catch(() => ({}));
                        setBudgetCapMsg({ ok: false, text: err.detail || "Failed to save budget cap." });
                      }
                    } catch {
                      setBudgetCapMsg({ ok: false, text: "Connection error. Please try again." });
                    } finally {
                      setBudgetCapSaving(false);
                    }
                  }}
                  className="bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] px-4 font-bold hover:bg-[#F28C28] transition duration-150 disabled:opacity-50"
                >
                  {budgetCapSaving ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* -------------------- TENANT ADMIN: ROUTING -------------------- */}
        {activeTab === "Routing" && (
          <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E] max-w-2xl">
            <h3 className="text-xl font-bold mb-2 font-mono">Routing Mode</h3>
            <p className="text-sm text-gray-600 mb-6 border-b-2 border-gray-100 pb-2">Choose how requests are routed for your organization.</p>

            <div className="space-y-6">
              <div>
                <label className="block text-sm font-extrabold mb-2 uppercase">Mode</label>
                <div className="space-y-2">
                  {[
                    { mode: "ECO", desc: "Maximize cost savings — keeps requests on cheaper models" },
                    { mode: "SMART", desc: "Balanced — automatically picks the right model per request" },
                    { mode: "PERFORMANCE", desc: "Maximize quality — always uses the top-tier model" },
                  ].map(({ mode, desc }) => (
                    <label key={mode} className="flex items-center gap-3 p-2.5 border-2 border-[#1E1E1E] cursor-pointer hover:bg-gray-50">
                      <input
                        type="radio"
                        name="routingMode"
                        value={mode}
                        checked={routingMode === mode}
                        onChange={() => setRoutingMode(mode)}
                        className="accent-[#F28C28]"
                      />
                      <div>
                        <span className="font-bold">{mode}</span> - <span className="text-sm text-gray-600">{desc}</span>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-sm font-extrabold mb-2 uppercase">Backup Provider</label>
                <select
                  value={fallbackProvider}
                  onChange={(e) => setFallbackProvider(e.target.value)}
                  className="w-full p-2.5 border-2 border-[#1E1E1E] outline-none"
                >
                  <option value="gemini">Gemini (Google DeepMind)</option>
                  <option value="groq">Groq (LPU Accelerator)</option>
                </select>
                <p className="text-xs text-gray-500 mt-1">Used automatically if the primary model provider is unavailable.</p>
              </div>

              {settingsMsg && (
                <div className={`p-3 border-2 text-sm font-semibold ${settingsMsg.ok ? "bg-green-50 border-green-500 text-green-700" : "bg-red-50 border-red-500 text-red-700"}`}>
                  {settingsMsg.ok ? "✓" : "⚠️"} {settingsMsg.text}
                </div>
              )}
              <button
                disabled={settingsSaving}
                onClick={async () => {
                  setSettingsSaving(true);
                  setSettingsMsg(null);
                  try {
                    const res = await fetch(`${BACKEND_URL}/v1/tenant/settings`, {
                      method: "PATCH",
                      headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${token}`,
                      },
                      body: JSON.stringify({ routing_mode: routingMode, fallback_provider: fallbackProvider }),
                    });
                    if (res.ok) {
                      setSettingsMsg({ ok: true, text: "Settings saved successfully." });
                    } else {
                      const err = await res.json().catch(() => ({}));
                      setSettingsMsg({ ok: false, text: err.detail || "Failed to save settings." });
                    }
                  } catch {
                    setSettingsMsg({ ok: false, text: "Connection error. Please try again." });
                  } finally {
                    setSettingsSaving(false);
                  }
                }}
                className="w-full bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] py-3 font-bold hover:bg-[#F28C28] hover:-translate-y-0.5 transition duration-150 disabled:opacity-50"
              >
                {settingsSaving ? "Saving..." : "Save Routing Settings"}
              </button>
            </div>
          </div>
        )}

        {/* -------------------- TENANT ADMIN: API KEYS -------------------- */}
        {activeTab === "API Keys" && (
          <div className="space-y-6 max-w-2xl">
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Active Key Fingerprint</h3>
              <p className="text-sm text-gray-600 mb-2">This is a fingerprint of your current key, not the key itself — it cannot be used to authenticate:</p>
              <div className="bg-[#F5F4F0] p-3 border-2 border-[#1E1E1E] font-mono text-sm break-all">
                {metrics?.api_key_hash || "Not available"}
              </div>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-2 font-mono">Generate a New Key</h3>
              <p className="text-sm text-gray-600 mb-4">
                Generating a new key immediately replaces your current one — update any integrations using the old key.
              </p>
              {rotateMsg && (
                <div className={`p-3 border-2 text-sm font-semibold mb-4 ${rotateMsg.ok ? "bg-green-50 border-green-500 text-green-700" : "bg-red-50 border-red-500 text-red-700"}`}>
                  {rotateMsg.ok ? "✓" : "⚠️"} {rotateMsg.text}
                </div>
              )}
              {revealedKey && (
                <div className="bg-[#F5F4F0] p-4 border-2 border-[#1E1E1E] font-mono font-bold text-sm mb-4 break-all select-all">
                  {revealedKey}
                </div>
              )}
              <button
                disabled={rotating}
                onClick={handleRotateKey}
                className="w-full bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] py-3 font-bold hover:bg-[#F28C28] transition duration-150 disabled:opacity-50"
              >
                {rotating ? "Generating..." : "Generate New Key"}
              </button>
            </div>
          </div>
        )}

        {/* -------------------- DEVELOPER: API KEY -------------------- */}
        {activeTab === "API Key" && (
          <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E] max-w-xl">
            <h3 className="text-xl font-bold mb-2 font-mono">Your Organization's API Key</h3>
            <p className="text-sm text-gray-600 mb-4">This key is shared across your organization and managed by your tenant admin.</p>
            <div className="bg-[#F5F4F0] p-4 border-2 border-[#1E1E1E] font-mono text-sm mb-4 break-all">
              Fingerprint: {metrics?.api_key_hash || "Not available"}
            </div>
            <p className="text-xs text-gray-600">
              Ask your tenant admin for the active key, or to generate a new one from their "API Keys" tab.
            </p>
          </div>
        )}

        {/* -------------------- DEVELOPER: DOCS & CODE SAMPLES -------------------- */}
        {activeTab === "Docs & Code Samples" && (
          <div className="space-y-6 max-w-3xl">
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Quickstart</h3>

              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-bold mb-2 font-mono">Python (Requests Library)</h4>
                  <pre className="bg-[#1E1E1E] text-white p-4 border-2 border-[#1E1E1E] font-mono text-sm overflow-x-auto">
{`import requests
import json

url = "${BACKEND_URL}/v1/chat/completions"
headers = {
    "X-API-Key": "<YOUR_API_KEY>",
    "Content-Type": "application/json"
}
payload = {
    "model": "hybrid-gateway",
    "messages": [{"role": "user", "content": "How do I implement binary search?"}],
    "stream": True
}

response = requests.post(url, headers=headers, json=payload, stream=True)
for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))`}
                  </pre>
                </div>

                <div>
                  <h4 className="text-sm font-bold mb-2 font-mono">Shell (cURL)</h4>
                  <pre className="bg-[#1E1E1E] text-white p-4 border-2 border-[#1E1E1E] font-mono text-sm overflow-x-auto">
{`curl -X POST "${BACKEND_URL}/v1/chat/completions" \\
  -H "X-API-Key: <YOUR_API_KEY>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "hybrid-gateway",
    "messages": [{ "role": "user", "content": "Explain inheritance." }],
    "stream": true
  }'`}
                  </pre>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* -------------------- DEVELOPER: USAGE -------------------- */}
        {activeTab === "Usage" && (
          <div className="space-y-6 max-w-3xl">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[5px_5px_0px_#1E1E1E]">
                <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Requests This Month</p>
                <h2 className="text-3xl font-extrabold text-[#F28C28]">{metrics?.total_requests ?? 0}</h2>
              </div>
              <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[5px_5px_0px_#1E1E1E]">
                <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Usage This Month</p>
                <h2 className="text-3xl font-extrabold text-[#F28C28]">₹{usageThisMonth.toFixed(4)}</h2>
              </div>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Recent Requests</h3>

              {!metrics?.recent_logs || metrics.recent_logs.length === 0 ? (
                <div className="bg-gray-50 p-4 border-2 border-dashed border-gray-300 text-center text-gray-500">
                  No requests recorded yet. Send your first API call using the quickstart code samples.
                </div>
              ) : (
                <div className="space-y-3 font-mono text-sm">
                  {metrics.recent_logs.map((log, index) => (
                    <div key={index} className="bg-[#F5F4F0] p-3 border-l-4 border-[#F28C28] border-y border-r border-y-gray-200 border-r-gray-200 flex justify-between items-center">
                      <div>
                        <span className="text-gray-500 font-bold">[{new Date(log.timestamp).toLocaleTimeString()}]</span>{" "}
                        <span className="font-bold text-[#1E1E1E]">{log.model_used}</span>{" "}
                        <span className="text-xs text-gray-500">({log.prompt_tokens + log.completion_tokens} tokens)</span>
                        {log.used_fallback && <span className="text-xs text-orange-600 ml-2">(via backup provider)</span>}
                      </div>
                      <div className="text-right">
                        <span className="font-extrabold text-[#F28C28]">₹{log.billed_usage_cost.toFixed(6)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* -------------------- SUPER_ADMIN: PLATFORM OVERVIEW -------------------- */}
        {activeTab === "Platform Overview" && (
          <div className="space-y-6 max-w-3xl">
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Revenue, Cost & Profit This Month</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Revenue</p>
                  <h2 className="text-2xl font-extrabold">₹{(adminOverview?.total_revenue ?? 0).toFixed(2)}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Real Cost (Providers)</p>
                  <h2 className="text-2xl font-extrabold">₹{(adminOverview?.total_cogs ?? 0).toFixed(2)}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Profit</p>
                  <h2 className={`text-2xl font-extrabold ${(adminOverview?.platform_profit ?? 0) < 0 ? "text-red-600" : "text-[#F28C28]"}`}>
                    ₹{(adminOverview?.platform_profit ?? 0).toFixed(2)}
                  </h2>
                </div>
              </div>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Tenants</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Active / Total</p>
                  <h2 className="text-2xl font-extrabold">{adminOverview?.active_tenant_count ?? 0} / {adminOverview?.total_tenant_count ?? 0}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Client Savings Delivered</p>
                  <h2 className="text-2xl font-extrabold">₹{(adminOverview?.total_reference_cost_saved ?? 0).toFixed(2)}</h2>
                </div>
              </div>
            </div>

            {adminTenants.some(t => t.profit_this_period < 0) && (
              <div className="bg-red-50 border-4 border-red-600 p-6 shadow-[6px_6px_0px_#7f1d1d]">
                <h3 className="text-lg font-bold text-red-700 mb-2 font-mono">Unprofitable Tenants Flagged</h3>
                <p className="text-sm text-red-700">
                  {adminTenants.filter(t => t.profit_this_period < 0).length} tenant(s) currently cost more to serve than they've been billed this period.
                  See the Tenants tab for details.
                </p>
              </div>
            )}
          </div>
        )}

        {/* -------------------- SUPER_ADMIN: TENANTS -------------------- */}
        {activeTab === "Tenants" && (
          <div className="max-w-5xl">
            <div className="bg-white border-4 border-[#1E1E1E] shadow-[6px_6px_0px_#1E1E1E] overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b-2 border-[#1E1E1E] text-left">
                    <th className="p-3 font-mono">Tenant</th>
                    <th className="p-3 font-mono">Plan</th>
                    <th className="p-3 font-mono">Revenue</th>
                    <th className="p-3 font-mono">Real Cost</th>
                    <th className="p-3 font-mono">Profit</th>
                    <th className="p-3 font-mono">Last Active</th>
                    <th className="p-3 font-mono">Capped by Plan</th>
                  </tr>
                </thead>
                <tbody>
                  {adminTenants.length === 0 ? (
                    <tr><td className="p-4 text-gray-500" colSpan={7}>No tenants provisioned yet.</td></tr>
                  ) : (
                    adminTenants.map((t) => (
                      <tr key={t.tenant_id} className={`border-b border-gray-200 ${t.churn_risk ? "bg-red-50" : ""}`}>
                        <td className="p-3 font-bold">{t.tenant_id}{!t.is_active && <span className="text-red-600 text-xs ml-1">(inactive)</span>}</td>
                        <td className="p-3">{t.plan_tier}</td>
                        <td className="p-3">₹{t.revenue_this_period.toFixed(2)}</td>
                        <td className="p-3">₹{t.cogs_this_period.toFixed(2)}</td>
                        <td className={`p-3 font-bold ${t.profit_this_period < 0 ? "text-red-600" : "text-green-700"}`}>₹{t.profit_this_period.toFixed(2)}</td>
                        <td className="p-3 text-gray-500">
                          {t.last_active ? new Date(t.last_active).toLocaleDateString() : "Never"}
                          {t.churn_risk && <span className="text-red-600 text-xs block">⚠ No usage in 7+ days</span>}
                        </td>
                        <td className="p-3">
                          {t.tier_capped_count > 0 ? (
                            <span className="text-orange-600 font-bold">{t.tier_capped_count} requests{t.plan_tier === "BASIC" && <span className="block text-xs font-normal">Upsell candidate</span>}</span>
                          ) : "—"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* -------------------- SUPER_ADMIN: INFRASTRUCTURE -------------------- */}
        {activeTab === "Infrastructure" && (
          <div className="space-y-6 max-w-3xl">
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-1 font-mono">Request Volume & Failover, Last 30 Days</h3>
              <p className="text-xs text-gray-500 mb-4">
                <span className="inline-block w-3 h-3 bg-[#E5E1D8] mr-1 align-middle"></span> Total requests
                <span className="inline-block w-3 h-3 bg-red-500 ml-4 mr-1 align-middle"></span> Failed over to backup provider
              </p>
              {adminTimeseries.length === 0 ? (
                <div className="bg-gray-50 p-4 border-2 border-dashed border-gray-300 text-center text-gray-500 text-sm">
                  Not enough platform activity yet to show a trend.
                </div>
              ) : (
                <RequestVolumeChart data={adminTimeseries} />
              )}
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Failover Activity This Month</h3>
              <p className="text-sm text-gray-600 mb-4">Times a primary model provider was unavailable and the request was automatically routed to a backup provider.</p>
              <h2 className="text-3xl font-extrabold text-[#F28C28]">{adminOverview?.fallback_trigger_count ?? 0}</h2>
              <p className="text-xs text-gray-500 mt-2">A rising count may indicate a provider is degrading — worth investigating which one via tenant logs.</p>
            </div>
          </div>
        )}

        {/* -------------------- SECURITY SETTINGS (ALL ROLES) -------------------- */}
        {activeTab === "Security Settings" && (
          <div className="max-w-lg space-y-6">
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">Change Password</h3>

              {pwdMsg && (
                <div className={`p-3 border-2 text-sm font-semibold mb-4 ${pwdMsg.ok ? "bg-green-50 border-green-500 text-green-700" : "bg-red-50 border-red-500 text-red-700"}`}>
                  {pwdMsg.ok ? "✓" : "⚠️"} {pwdMsg.text}
                </div>
              )}

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-bold mb-1">Current Password</label>
                  <input
                    type="password"
                    value={currentPwd}
                    onChange={(e) => setCurrentPwd(e.target.value)}
                    className="w-full p-2.5 border-2 border-[#1E1E1E] outline-none focus:border-[#F28C28]"
                    placeholder="••••••••"
                  />
                </div>
                <div>
                  <label className="block text-sm font-bold mb-1">New Password</label>
                  <input
                    type="password"
                    value={newPwd}
                    onChange={(e) => setNewPwd(e.target.value)}
                    className="w-full p-2.5 border-2 border-[#1E1E1E] outline-none focus:border-[#F28C28]"
                    placeholder="Min. 8 characters"
                  />
                </div>
                <div>
                  <label className="block text-sm font-bold mb-1">Confirm New Password</label>
                  <input
                    type="password"
                    value={confirmPwd}
                    onChange={(e) => setConfirmPwd(e.target.value)}
                    className="w-full p-2.5 border-2 border-[#1E1E1E] outline-none focus:border-[#F28C28]"
                    placeholder="••••••••"
                  />
                </div>

                <button
                  disabled={pwdSaving}
                  onClick={async () => {
                    setPwdMsg(null);
                    if (!currentPwd || !newPwd || !confirmPwd) {
                      setPwdMsg({ ok: false, text: "All fields are required." });
                      return;
                    }
                    if (newPwd !== confirmPwd) {
                      setPwdMsg({ ok: false, text: "New passwords do not match." });
                      return;
                    }
                    if (newPwd.length < 8) {
                      setPwdMsg({ ok: false, text: "New password must be at least 8 characters." });
                      return;
                    }
                    setPwdSaving(true);
                    try {
                      const res = await fetch(`${BACKEND_URL}/v1/auth/change-password`, {
                        method: "POST",
                        headers: {
                          "Content-Type": "application/json",
                          Authorization: `Bearer ${token}`,
                        },
                        body: JSON.stringify({ current_password: currentPwd, new_password: newPwd }),
                      });
                      if (res.ok) {
                        setPwdMsg({ ok: true, text: "Password updated. Use your new password on next login." });
                        setCurrentPwd(""); setNewPwd(""); setConfirmPwd("");
                      } else {
                        const err = await res.json().catch(() => ({}));
                        setPwdMsg({ ok: false, text: err.detail || "Failed to update password." });
                      }
                    } catch {
                      setPwdMsg({ ok: false, text: "Connection error. Please try again." });
                    } finally {
                      setPwdSaving(false);
                    }
                  }}
                  className="w-full bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] py-2.5 font-bold hover:bg-[#F28C28] transition duration-150 disabled:opacity-50"
                >
                  {pwdSaving ? "Updating..." : "Update Password"}
                </button>
              </div>
            </div>
          </div>
        )}

      </main>

    </div>
  );
}
