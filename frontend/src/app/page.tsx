"use client";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "https://ahmednav-hybrid-router.hf.space";

export default function Home() {
  const redirectToPayment = (url: string) => {
    console.log(`Redirecting to payment page: ${url}`);
    window.open(url, "_blank");
  };

  return (
    <div className="min-h-screen bg-[#F5F4F0] text-[#1E1E1E] p-8 font-sans">
      <div className="max-w-4xl mx-auto">
        
        {/* Brand Header Card */}
        <header className="bg-white border-4 border-[#1E1E1E] p-8 mb-8 shadow-[8px_8px_0px_#1E1E1E]">
          <h1 className="text-4xl font-extrabold tracking-tight mb-4 font-mono">
            The Gateway that <span className="bg-[#F28C28] text-white px-2 py-1 rotate-[-1.5deg] inline-block">scrubs PII</span> before it leaves your servers
          </h1>
          <p className="text-lg text-gray-700 max-w-3xl">
            An intelligent cost-optimization router that ensures your LLM cost-efficiency layer doesn't become your compliance liability. 
            Features local sub-millisecond route calculations, real-time Groq/Gemini failover matrices, and local data sanitization.
          </p>
          <div className="mt-6 flex gap-4">
            <a 
              href="/login" 
              className="bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] px-6 py-2 font-semibold hover:bg-[#F28C28] hover:text-white transition duration-150"
            >
              Sign In to Console
            </a>
          </div>
        </header>

        {/* Technical Differentiators Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
          <div className="bg-white border-3 border-[#1E1E1E] p-6 shadow-[5px_5px_0px_#1E1E1E] hover:-translate-y-1 transition duration-150">
            <h3 className="text-xl font-bold mb-2">⚡ Sub-Millisecond Overhead</h3>
            <p className="text-gray-600">Local semantic caching checks route maps and classifies queries locally to guarantee zero network route delays.</p>
          </div>
          <div className="bg-white border-3 border-[#1E1E1E] p-6 shadow-[5px_5px_0px_#1E1E1E] hover:-translate-y-1 transition duration-150">
            <h3 className="text-xl font-bold mb-2">🔒 Automatic Data Scrubbing</h3>
            <p className="text-gray-600">Built-in PII analyzer monitors outbound requests locally, identifying and masking sensitive details before LLM transit.</p>
          </div>
          <div className="bg-white border-3 border-[#1E1E1E] p-6 shadow-[5px_5px_0px_#1E1E1E] hover:-translate-y-1 transition duration-150">
            <h3 className="text-xl font-bold mb-2">🚀 Resilient Failover</h3>
            <p className="text-gray-600">Zero downtime failover policies. Automatically redirects traffic to backup clusters if primary inference systems fail.</p>
          </div>
        </div>

        {/* Pricing Area */}
        <div className="bg-white border-4 border-[#1E1E1E] p-8 mb-8 shadow-[8px_8px_0px_#1E1E1E]">
          <div className="text-center mb-8">
            <h2 className="text-3xl font-extrabold mb-2">B2B Developer SaaS Plans</h2>
            <p className="text-gray-600">Choose a tier to match your application demand and compliance posture.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Basic Plan */}
            <div className="border-3 border-[#1E1E1E] p-6 bg-[#F5F4F0] flex flex-col justify-between shadow-[5px_5px_0px_#1E1E1E]">
              <div>
                <h3 className="text-2xl font-bold mb-2">Developer Basic</h3>
                <div className="text-3xl font-extrabold mb-4">₹1,999 <span className="text-base font-normal text-gray-500">/ month</span></div>
                <ul className="space-y-2 mb-6">
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Dynamic Groq/Gemini Routing</li>
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Local PII Sanitization Guard</li>
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Cap to 60 requests/minute</li>
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Standard Admin Console Access</li>
                </ul>
              </div>
              <button 
                onClick={() => redirectToPayment("https://rzp.io/rzp/XNQO1xe7")}
                className="w-full bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] py-2 font-bold hover:bg-[#F28C28] hover:-translate-y-0.5 hover:shadow-[3px_3px_0px_#1E1E1E] transition duration-100"
              >
                Buy Developer Basic
              </button>
            </div>

            {/* Premium Plan */}
            <div className="border-3 border-[#F28C28] p-6 bg-[#FFFDF9] flex flex-col justify-between shadow-[6px_6px_0px_#F28C28]">
              <div>
                <h3 className="text-2xl font-bold mb-2 text-[#F28C28]">Enterprise Pro</h3>
                <div className="text-3xl font-extrabold mb-4">₹6,999 <span className="text-base font-normal text-gray-500">/ month</span></div>
                <ul className="space-y-2 mb-6">
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Dynamic Groq/Gemini Routing</li>
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Local PII Sanitization Guard</li>
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Elevated Limits (1,000 req/min)</li>
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Custom Failover Provider Override</li>
                  <li className="flex items-center gap-2"><span className="text-[#F28C28] font-bold">✓</span> Full ROI Analytics Suite</li>
                </ul>
              </div>
              <button 
                onClick={() => redirectToPayment("https://rzp.io/rzp/sn56YqL")}
                className="w-full bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] py-2 font-bold hover:bg-[#F28C28] hover:-translate-y-0.5 hover:shadow-[3px_3px_0px_#1E1E1E] transition duration-100"
              >
                Buy Enterprise Pro
              </button>
            </div>
          </div>
        </div>

        {/* Disclaimer Footer Block */}
        <div className="bg-[#FDF9F6] border-2 border-[#1E1E1E] p-4 text-sm text-gray-500">
          <strong>Compliance Transparency Disclosure:</strong> Hybrid Router reduces exposure to third-party APIs by sanitizing records on host systems. However, users must verify local network variables to meet final HIPAA/GDPR validation standards.
        </div>

      </div>
    </div>
  );
}
