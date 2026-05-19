
'use client'

import { useState, Suspense } from 'react'
import { signIn, useSession } from 'next-auth/react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import Link from 'next/link'
import { Sparkles, ArrowLeft } from 'lucide-react'

function LoginForm() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const router = useRouter()
  const searchParams = useSearchParams()
  const message = searchParams.get('message')
  const errorParam = searchParams.get('error')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      const result = await signIn('credentials', {
        redirect: false,
        email,
        password,
      });

      if (result?.error) {
        setError('Invalid credentials or account not activated yet');
      } else if (result?.ok) {
        router.push(searchParams.get('callbackUrl') || '/workspaces');
      } else {
        setError('Login failed. Please try again.');
      }
    } catch (err) {
      setError('An error occurred. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card className="w-full max-w-md border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-2xl shadow-violet-900/20">
      <CardHeader className="space-y-1 pb-6">
        <CardTitle className="text-2xl font-bold tracking-tight text-white">Welcome back</CardTitle>
        <p className="text-sm text-slate-400">Enter your credentials to access your workspaces</p>
      </CardHeader>
      <CardContent>
        {message && <p className="text-sm text-emerald-400 mb-4 bg-emerald-400/10 p-3 rounded-md border border-emerald-400/20">{message}</p>}
        {errorParam && <p className="text-sm text-red-400 mb-4 bg-red-400/10 p-3 rounded-md border border-red-400/20">{errorParam}</p>}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email" className="text-slate-300">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={isLoading} className="border-slate-700 bg-slate-950/50 text-white focus-visible:ring-violet-500" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password" className="text-slate-300">Password</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required disabled={isLoading} className="border-slate-700 bg-slate-950/50 text-white focus-visible:ring-violet-500" />
          </div>
          {error && <p className="text-sm text-red-400 bg-red-400/10 p-3 rounded-md border border-red-400/20">{error}</p>}
          <Button type="submit" className="w-full bg-violet-600 hover:bg-violet-700 text-white mt-2 h-11" disabled={isLoading}>
            {isLoading ? 'Authenticating...' : 'Sign In'}
          </Button>
        </form>
        <div className="mt-6 text-center">
          <Link href="/signup" className="text-sm text-violet-400 hover:text-violet-300 transition-colors">
            Don't have an account? Sign up today
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}

export default function LoginPage() {
  return (
    <div className="relative min-h-screen bg-slate-950 font-sans text-slate-50 flex flex-col">
      {/* Dynamic Background */}
      <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[10%] left-[20%] h-[50%] w-[40%] rounded-full bg-violet-600/10 blur-[100px]" />
        <div className="absolute bottom-[10%] right-[20%] h-[40%] w-[30%] rounded-full bg-indigo-600/10 blur-[120px]" />
        <div className="absolute inset-0 bg-[url('/grid.svg')] bg-center [mask-image:linear-gradient(180deg,white,rgba(255,255,255,0))]" />
      </div>

      {/* Header */}
      <header className="relative z-20 flex items-center justify-between px-6 py-6 lg:px-12">
        <Link href="/" className="flex items-center gap-2 group">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-500/30 transition-transform group-hover:scale-105">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">QAPtain</span>
        </Link>
        <Link href="/" className="flex items-center text-sm font-medium text-slate-400 transition-colors hover:text-white">
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Home
        </Link>
      </header>

      {/* Main Content */}
      <main className="relative z-10 flex flex-1 flex-col items-center justify-center px-6 py-12">
        <Suspense fallback={<div className="text-violet-400 animate-pulse">Loading secure environment...</div>}>
          <LoginForm />
        </Suspense>
      </main>

      {/* Footer */}
      <footer className="relative z-10 py-6 text-center">
        <p className="text-xs text-slate-600">Secure connection • Authenticated via QAPtain Core</p>
      </footer>
    </div>
  )
}
