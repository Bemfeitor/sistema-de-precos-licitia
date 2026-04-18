'use client';

import { useState } from 'react';

interface DebugResult {
  success: boolean;
  status?: number;
  data?: unknown;
  error?: string;
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Erro desconhecido';
}

export default function DebugPage() {
  const [apiUrl, setApiUrl] = useState(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000');
  const [result, setResult] = useState<DebugResult | null>(null);
  const [loading, setLoading] = useState(false);

  const testHealth = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/health`);
      const data = await res.json();
      setResult({ success: res.ok, status: res.status, data });
    } catch (error: unknown) {
      setResult({ success: false, error: getErrorMessage(error) });
    } finally {
      setLoading(false);
    }
  };

  const testLogin = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'test@example.com', password: 'test123' }),
      });
      const data = await res.json();
      setResult({ success: res.ok, status: res.status, data });
    } catch (error: unknown) {
      setResult({ success: false, error: getErrorMessage(error) });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#09090b] text-white p-8">
      <h1 className="text-2xl font-bold mb-6">Debug - Teste de API</h1>
      
      <div className="mb-6">
        <label className="block text-sm text-zinc-400 mb-2">API URL:</label>
        <input 
          type="text" 
          value={apiUrl}
          onChange={(e) => setApiUrl(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded px-4 py-2 w-full max-w-md"
        />
      </div>

      <div className="flex gap-4 mb-6">
        <button 
          onClick={testHealth}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          Testar Health
        </button>
        <button 
          onClick={testLogin}
          disabled={loading}
          className="px-4 py-2 bg-green-600 rounded hover:bg-green-700 disabled:opacity-50"
        >
          Testar Login
        </button>
      </div>

      {result && (
        <div className="bg-zinc-800 border border-zinc-700 rounded p-4">
          <h2 className="font-bold mb-2">Resultado:</h2>
          <pre className="text-sm text-zinc-300 overflow-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}

      <div className="mt-8 text-sm text-zinc-400">
        <p>Credenciais de teste:</p>
        <p>Email: test@example.com</p>
        <p>Senha: test123</p>
      </div>
    </div>
  );
}
