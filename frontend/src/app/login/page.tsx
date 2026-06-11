'use client';

import { useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import Link from 'next/link';
import { Sparkles, ArrowLeft } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

function LoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const message = searchParams.get('message');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const res = await fetch(`${API_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (res.ok) {
        const data = await res.json();
        localStorage.setItem('qaptain_token', data.access_token);
        router.push(searchParams.get('callbackUrl') || '/workspaces');
      } else {
        const data = await res.json().catch(() => ({}));
        const detail = data.detail;
        setError(Array.isArray(detail)
          ? detail.map((e: { msg: string }) => e.msg).join(', ')
          : (detail || 'Invalid email or password'));
      }
    } catch {
      setError('Connection error. Is the backend running?');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Card className="w-full max-w-md border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-2xl shadow-violet-900/20">
      <CardHeader className="space-y-1 pb-6">
        <CardTitle className="text-2xl font-bold tracking-tight text-white">Welcome back</CardTitle>
        <p className="text-sm text-slate-400">Enter your credentials to access your workspaces</p>
      </CardHeader>
      <CardContent>
        {message && (
          <p className="text-sm text-emerald-400 mb-4 bg-emerald-400/10 p-3 rounded-md border border-emerald-400/20">
            {message}
          </p>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email" className="text-slate-300">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={isLoading}
              className="border-slate-700 bg-slate-950/50 text-white focus-visible:ring-violet-500"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password" className="text-slate-300">Password</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={isLoading}
              className="border-slate-700 bg-slate-950/50 text-white focus-visible:ring-violet-500"
            />
          </div>
          {error && (
            <p className="text-sm text-red-400 bg-red-400/10 p-3 rounded-md border border-red-400/20">{error}</p>
          )}
          <Button
            type="submit"
            className="w-full bg-violet-600 hover:bg-violet-700 text-white mt-2 h-11"
            disabled={isLoading}
          >
            {isLoading ? 'Authenticating...' : 'Sign In'}
          </Button>
        </form>
        <div className="mt-6 text-center">
          <Link href="/signup" className="text-sm text-violet-400 hover:text-violet-300 transition-colors">
            Don&apos;t have an account? Sign up today
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <div className="relative min-h-screen bg-slate-950 font-sans text-slate-50 flex flex-col">
      <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[10%] left-[20%] h-[50%] w-[40%] rounded-full bg-violet-600/10 blur-[100px]" />
        <div className="absolute bottom-[10%] right-[20%] h-[40%] w-[30%] rounded-full bg-indigo-600/10 blur-[120px]" />
      </div>
      <header className="relative z-20 flex items-center justify-between px-6 py-6 lg:px-12">
        <Link href="/" className="flex items-center gap-2 group">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-500/30 transition-transform group-hover:scale-105">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">QAptain</span>
        </Link>
        <Link href="/" className="flex items-center text-sm font-medium text-slate-400 transition-colors hover:text-white">
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Home
        </Link>
      </header>
      <main className="relative z-10 flex flex-1 flex-col items-center justify-center px-6 py-12">
        <Suspense fallback={<div className="text-violet-400 animate-pulse">Loading...</div>}>
          <LoginForm />
        </Suspense>
      </main>
      <footer className="relative z-10 py-6 text-center">
        <p className="text-xs text-slate-600">Secure connection • Authenticated via QAptain Core</p>
      </footer>
    </div>
  );
}
