
'use client'

import { useState, Suspense } from 'react'
import { signIn, useSession } from 'next-auth/react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import Link from 'next/link'

function LoginForm() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const router = useRouter()
  const searchParams = useSearchParams()
  const message = searchParams.get('message')
  const errorParam = searchParams.get('error')
  const { update: updateSession } = useSession()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      console.log('[Login] Attempting to sign in with email:', email)
      const result = await signIn('credentials', {
        redirect: false,
        email,
        password,
      });

      console.log('[Login] Sign in result:', result);

      if (result?.error) {
        setError('Invalid email or password');
        console.error('[Login] Sign in error:', result.error);
      } else if (result?.ok) {
        // Manual redirect on success
        console.log('[Login] Sign in successful, manually redirecting...');
        router.push('/');
      } else {
        setError('Login failed. Please try again.');
        console.error('[Login] Sign in failed - no error but not ok');
      }
    } catch (err) {
      console.error('[Login] Exception during sign in:', err)
      setError('An error occurred. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Login</CardTitle>
      </CardHeader>
      <CardContent>
        {message && <p className="text-green-500 mb-4">{message}</p>}
        {errorParam && <p className="text-red-500 mb-4">{errorParam}</p>}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={isLoading} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required disabled={isLoading} />
          </div>
          {error && <p className="text-red-500">{error}</p>}
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? 'Logging in...' : 'Login'}
          </Button>
        </form>
        <div className="mt-4 text-center">
          <Link href="/signup" className="text-sm text-blue-500 hover:underline">
            Don't have an account? Sign up
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}

export default function LoginPage() {
  return (
    <div className="flex justify-center items-center h-screen">
      <Suspense fallback={<div>Loading...</div>}>
        <LoginForm />
      </Suspense>
    </div>
  )
}
