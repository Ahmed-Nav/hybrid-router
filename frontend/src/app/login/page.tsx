"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "https://ahmednav-hybrid-router.hf.space";

export default function Login() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setError("Both username and password are required.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${BACKEND_URL}/v1/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
      });

      if (response.ok) {
        const data = await response.json();
        // Save auth details
        localStorage.setItem("auth_token", data.access_token);
        localStorage.setItem("user_info", JSON.stringify(data.user_info));
        
        // Redirect to dashboard
        router.push("/dashboard");
      } else {
        const errData = await response.json().catch(() => ({ detail: "Authentication Denied" }));
        setError(errData.detail || "Invalid username or password.");
      }
    } catch (err: any) {
      setError("Connection to API gateway failed. Verify the backend is running.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F5F4F0] flex justify-center items-center p-4">
      <div className="bg-white border-4 border-[#1E1E1E] p-8 w-full max-w-md shadow-[8px_8px_0px_#1E1E1E]">
        <h2 className="text-3xl font-extrabold mb-6 font-mono border-b-2 border-gray-100 pb-2">
          Log In
        </h2>
        
        {error && (
          <div className="bg-red-50 border-2 border-red-500 text-red-700 p-3 mb-4 text-sm font-semibold">
            ⚠️ {error}
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-sm font-bold mb-1">Username</label>
            <input 
              type="text" 
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full p-2.5 border-2 border-[#1E1E1E] outline-none focus:border-[#F28C28]"
              placeholder="e.g., cto_enterprise"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-bold mb-1">Password</label>
            <input 
              type="password" 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full p-2.5 border-2 border-[#1E1E1E] outline-none focus:border-[#F28C28]"
              placeholder="••••••••"
              required
            />
          </div>
          <button 
            type="submit"
            disabled={loading}
            className="w-full bg-[#1E1E1E] text-white border-2 border-[#1E1E1E] py-2.5 font-bold hover:bg-[#F28C28] hover:-translate-y-0.5 transition duration-100 disabled:opacity-50"
          >
            {loading ? "Logging in..." : "Log In"}
          </button>
        </form>
        
        <div className="mt-4 p-3 bg-[#FFFDF9] border border-[#F28C28] text-xs text-gray-600 font-medium">
          💡 <strong>Just signed up?</strong> Check your registration inbox (and spam folder) for your onboarding email containing your secure API key and dashboard password.
        </div>
        
        <div className="mt-6 text-center">
          <a href="/" className="text-sm font-semibold text-[#F28C28] hover:underline">
            ← Return to Landing Page
          </a>
        </div>
      </div>
    </div>
  );
}
