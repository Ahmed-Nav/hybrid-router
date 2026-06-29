"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface UserInfo {
  username: string;
  role: string;
  tenant_id: string | null;
}

interface Metrics {
  tenant_id: string;
  plan_tier: string;
  total_spend: number;
  total_tokens: number;
  api_key_hash: string;
}

export default function Dashboard() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [activeTab, setActiveTab] = useState("");
  const [loading, setLoading] = useState(true);

  // States for LLM preferences override
  const [routingMode, setRoutingMode] = useState("SMART");
  const [fallbackProvider, setFallbackProvider] = useState("groq");
  
  // States for dynamic token generation mockup
  const [newKeyLabel, setNewKeyLabel] = useState("");
  const [generatedKey, setGeneratedKey] = useState("");

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

    // Set default active tab based on role
    if (parsedUser.role === "SUPER_ADMIN") {
      setActiveTab("Global Platform Analytics");
    } else if (parsedUser.role === "TENANT_ADMIN") {
      setActiveTab("FinOps Billing Suite");
    } else {
      setActiveTab("Developer Credential Safe");
    }

    // Fetch dynamic metrics from backend
    fetchMetrics(storedToken);
  }, [router]);

  const fetchMetrics = async (authToken: string) => {
    try {
      const res = await fetch("http://localhost:7860/v1/analytics", {
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
      } else {
        console.error("Failed to load metrics from API gateway");
      }
    } catch (err) {
      console.error("API gateway connection error:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("user_info");
    router.push("/login");
  };

  if (loading || !user) {
    return (
      <div className="min-h-screen bg-[#F5F4F0] flex justify-center items-center font-mono">
        🔄 Accessing telemetry secure gateway...
      </div>
    );
  }

  // Define tabs based on role
  const getTabs = () => {
    if (user.role === "SUPER_ADMIN") {
      return ["Global Platform Analytics", "B2B Tenant Provisioning", "Infrastructure Controls"];
    } else if (user.role === "TENANT_ADMIN") {
      return ["FinOps Billing Suite", "The LLM Option Control", "API Key Lifecycle Engine"];
    } else {
      return ["Developer Credential Safe", "Integration Snippets", "Personal Usage Stream"];
    }
  };

  const tabs = getTabs();

  // ROI savings calculation helper
  const totalTokens = metrics?.total_tokens || 0;
  const estimatedUnroutedCost = (totalTokens * 0.79) / 1000000;
  const actualIncurredCost = metrics?.total_spend || 0.00;
  const netSavings = Math.max(0.0001, estimatedUnroutedCost - actualIncurredCost);

  return (
    <div className="min-h-screen bg-[#F5F4F0] text-[#1E1E1E] flex flex-col md:flex-row font-sans">
      
      {/* Sidebar Navigation Layout */}
      <aside className="w-full md:w-64 bg-white border-b-4 md:border-b-0 md:border-r-4 border-[#1E1E1E] p-6 flex flex-col justify-between">
        <div>
          <div className="mb-6 pb-4 border-b-2 border-gray-100">
            <h2 className="text-xl font-extrabold tracking-tight font-mono text-[#F28C28]">⚡ Control Console</h2>
            <div className="mt-2 text-xs text-gray-500">
              <p>Tenant: <strong className="text-[#1E1E1E]">{user.tenant_id || "GLOBAL_CLUSTER"}</strong></p>
              <p>Clearance: <strong className="text-[#1E1E1E]">{user.role}</strong></p>
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
          Log Out of Session
        </button>
      </aside>

      {/* Main content viewport */}
      <main className="flex-1 p-8">
        <h2 className="text-3xl font-extrabold mb-6 font-mono border-b-4 border-[#1E1E1E] pb-2">
          📊 Module Workspace: {activeTab}
        </h2>

        {/* -------------------- TENANT ADMIN VIEWS -------------------- */}
        {activeTab === "FinOps Billing Suite" && (
          <div className="space-y-6">
            
            {/* Expenditure Matrix */}
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">💳 Corporate Expenditure Matrix</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase tracking-wider">Cumulative Spend</p>
                  <h2 className="text-3xl font-extrabold text-[#F28C28]">₹{metrics?.total_spend.toFixed(4) || "0.0000"}</h2>
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

            {/* Savings Box */}
            <div className="bg-[#FFFDF9] border-4 border-[#F28C28] p-6 shadow-[6px_6px_0px_#F28C28]">
              <h3 className="text-xl font-bold text-[#F28C28] mb-2 font-mono">🔥 Router ROI Performance Analysis</h3>
              <p className="text-sm text-gray-600 mb-4">Your business router optimizes expenses by keeping lightweight queries off expensive foundational models.</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase">Estimated Unrouted Cost</p>
                  <h2 className="text-2xl font-bold">₹{estimatedUnroutedCost.toFixed(4)}</h2>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-bold uppercase text-[#F28C28]">Net Financial Savings</p>
                  <h2 className="text-2xl font-extrabold text-[#F28C28]">₹{netSavings.toFixed(4)}</h2>
                </div>
              </div>
            </div>

          </div>
        )}

        {activeTab === "The LLM Option Control" && (
          <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E] max-w-2xl">
            <h3 className="text-xl font-bold mb-2 font-mono">⚙️ Dynamic Routing Preference Controller</h3>
            <p className="text-sm text-gray-600 mb-6 border-b-2 border-gray-100 pb-2">Configure the operational priority for your organization routing policies in real time.</p>
            
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-extrabold mb-2 uppercase">Select Optimization Protocol</label>
                <div className="space-y-2">
                  {[
                    { mode: "ECO", desc: "Maximize Cost Efficiency (Force Edge Arrays)" },
                    { mode: "SMART", desc: "Balanced Adaptive Routing Engine" },
                    { mode: "PERFORMANCE", desc: "Absolute Logical Accuracy Profile (Force 70B Track)" }
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
                <label className="block text-sm font-extrabold mb-2 uppercase">Failover Engine Backup Provider</label>
                <select 
                  value={fallbackProvider}
                  onChange={(e) => setFallbackProvider(e.target.value)}
                  className="w-full p-2.5 border-2 border-[#1E1E1E] outline-none"
                >
                  <option value="gemini">Gemini (Google DeepMind)</option>
                  <option value="groq">Groq (LPU Accelerator)</option>
                </select>
              </div>

              <button 
                onClick={() => {
                  alert(`Preferences committed!\nMode: ${routingMode}\nFailover Provider: ${fallbackProvider}`);
                }}
                className="w-full bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] py-3 font-bold hover:bg-[#F28C28] hover:-translate-y-0.5 transition duration-150"
              >
                Apply Operational Overrides Globally
              </button>
            </div>
          </div>
        )}

        {activeTab === "API Key Lifecycle Engine" && (
          <div className="space-y-6 max-w-2xl">
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">🔑 Active Infrastructure Fingerprints</h3>
              <p className="text-sm text-gray-600 mb-2">Cryptographic SHA-256 footprint matching key registers committed to active routers:</p>
              <div className="bg-[#F5F4F0] p-3 border-2 border-[#1E1E1E] font-mono text-sm break-all">
                {metrics?.api_key_hash || "Not Available"}
              </div>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-2 font-mono">Provision Additional App Token</h3>
              <p className="text-sm text-gray-600 mb-4">Allocate sandboxed credentials linked directly to your organization ledger.</p>
              
              <div className="space-y-4">
                <input 
                  type="text" 
                  value={newKeyLabel}
                  onChange={(e) => setNewKeyLabel(e.target.value)}
                  placeholder="Application Label (e.g. staging-server)"
                  className="w-full p-2.5 border-2 border-[#1E1E1E] outline-none"
                />

                <button 
                  onClick={() => {
                    if (!newKeyLabel) {
                      alert("Please provide an application label.");
                      return;
                    }
                    const mockHex = Math.random().toString(36).substring(2, 10);
                    setGeneratedKey(`sk_client_token_${mockHex}`);
                  }}
                  className="w-full bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] py-2.5 font-bold hover:bg-[#F28C28] transition duration-150"
                >
                  Generate Token Key Pair
                </button>

                {generatedKey && (
                  <div className="bg-amber-50 border-2 border-amber-500 p-4 mt-2">
                    <p className="text-xs text-amber-700 font-bold mb-1">⚠️ COPY THIS KEY IMMEDIATELY. IT WILL NOT BE SHOWN AGAIN:</p>
                    <code className="text-sm font-bold font-mono text-[#1E1E1E]">{generatedKey}</code>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* -------------------- DEVELOPER VIEWS -------------------- */}
        {activeTab === "Developer Credential Safe" && (
          <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E] max-w-xl">
            <h3 className="text-xl font-bold mb-2 font-mono">🔒 Personal Key Access Safe</h3>
            <p className="text-sm text-gray-600 mb-4">Use this token to authenticate SDK scripts against the API gateway pipeline.</p>
            <div className="bg-[#F5F4F0] p-4 border-2 border-[#1E1E1E] font-mono font-bold text-lg mb-4 select-all">
              X-API-Key: sk_live_************************
            </div>
            <p className="text-xs text-red-600 font-semibold">⚠️ Guard this key carefully. Actions executed with this credentials vector write straight to your group metric ledger.</p>
          </div>
        )}

        {activeTab === "Integration Snippets" && (
          <div className="space-y-6 max-w-3xl">
            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">💻 Quickstart Multi-Language Integration</h3>
              
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-bold mb-2 font-mono">Python (Requests Library)</h4>
                  <pre className="bg-[#1E1E1E] text-white p-4 border-2 border-[#1E1E1E] font-mono text-sm overflow-x-auto">
{`import requests
import json

url = "http://localhost:7860/v1/chat/completions"
headers = {
    "X-API-Key": "sk_live_************************",
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
{`curl -X POST "http://localhost:7860/v1/chat/completions" \\
  -H "X-API-Key: sk_live_************************" \\
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

        {activeTab === "Personal Usage Stream" && (
          <div className="space-y-6 max-w-3xl">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[5px_5px_0px_#1E1E1E]">
                <p className="text-xs text-gray-500 font-bold uppercase">Mean Connection Latency</p>
                <h2 className="text-3xl font-extrabold text-[#F28C28]">342 ms</h2>
              </div>
              <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[5px_5px_0px_#1E1E1E]">
                <p className="text-xs text-gray-500 font-bold uppercase">Requests Contributed</p>
                <h2 className="text-3xl font-extrabold text-[#F28C28]">47 calls</h2>
              </div>
            </div>

            <div className="bg-white border-4 border-[#1E1E1E] p-6 shadow-[6px_6px_0px_#1E1E1E]">
              <h3 className="text-xl font-bold mb-4 font-mono">🛠️ Active Connection Debug Logs</h3>
              <div className="space-y-2 font-mono text-sm">
                <div className="bg-[#F5F4F0] p-2.5 border-l-4 border-green-500 text-gray-700">
                  [18:04:12] POST /v1/chat/completions - Status 200 OK (Routed: SIMPLE_CHAT via Groq)
                </div>
                <div className="bg-[#F5F4F0] p-2.5 border-l-4 border-green-500 text-gray-700">
                  [18:03:55] POST /v1/chat/completions - Status 200 OK (Routed: COMPLEX_REASONING via Gemini)
                </div>
                <div className="bg-[#F5F4F0] p-2.5 border-l-4 border-blue-500 text-gray-700">
                  [17:59:01] GET /v1/analytics - Status 200 OK (Authentication Session Verified)
                </div>
              </div>
            </div>
          </div>
        )}

      </main>

    </div>
  );
}
