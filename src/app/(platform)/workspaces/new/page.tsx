'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export default function NewWorkspacePage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [baseUrl, setBaseUrl] = useState('');

  const [authName, setAuthName] = useState('Primary');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [labName, setLabName] = useState('');
  const [roleHint, setRoleHint] = useState('ADMIN');

  const [workspaceId, setWorkspaceId] = useState('');
  const [environmentId, setEnvironmentId] = useState('');
  const [authProfileId, setAuthProfileId] = useState('');

  const createWorkspace = async () => {
    setErr('');
    setLoading(true);
    try {
      const r = await fetch('/api/v1/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, baseUrl }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Failed');
      setWorkspaceId(d.workspace.id);
      const env = d.workspace.environments?.[0];
      if (env) setEnvironmentId(env.id);
      setStep(2);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Error');
    } finally {
      setLoading(false);
    }
  };

  const saveAuth = async () => {
    setErr('');
    setLoading(true);
    try {
      const r = await fetch(`/api/v1/workspaces/${workspaceId}/auth-profiles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: authName,
          blueprint: {
            steps: [
              { type: 'text', field: 'username' },
              { type: 'password', field: 'password' },
              ...(labName ? [{ type: 'dropdown', field: 'location' }] : []),
            ],
          },
          username,
          password,
          labName: labName || null,
          roleHint,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Failed');
      setAuthProfileId(d.authProfile.id);
      setStep(3);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Error');
    } finally {
      setLoading(false);
    }
  };

  const startDiscovery = async () => {
    setErr('');
    setLoading(true);
    try {
      const r = await fetch(`/api/v1/workspaces/${workspaceId}/discovery`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ environmentId, authProfileId }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Failed');
      router.push(`/workspaces/${workspaceId}?discovery=${d.discoveryRun.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-lg space-y-8 p-6 lg:p-10">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">New workspace</h1>
        <p className="mt-1 text-sm text-muted-foreground">Three steps: application URL, authentication, discovery.</p>
      </div>

      {err && <p className="text-sm text-red-600">{err}</p>}

      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>1 · Application</CardTitle>
            <CardDescription>Base URL used for Playwright navigation and discovery.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme ERP" />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
            </div>
            <div className="space-y-2">
              <Label>Base URL</Label>
              <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://app.example.com" />
            </div>
            <Button className="w-full" disabled={loading || !name || !baseUrl} onClick={createWorkspace}>
              Continue
            </Button>
          </CardContent>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>2 · Authentication profile</CardTitle>
            <CardDescription>Stored encrypted at rest. Used by discovery and execution.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Profile name</Label>
              <Input value={authName} onChange={(e) => setAuthName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Username</Label>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
            </div>
            <div className="space-y-2">
              <Label>Password</Label>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Lab / location label (optional)</Label>
              <Input value={labName} onChange={(e) => setLabName(e.target.value)} placeholder="For multi-step admin login" />
            </div>
            <div className="space-y-2">
              <Label>Role hint</Label>
              <Select value={roleHint} onValueChange={setRoleHint}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ADMIN">ADMIN (location picker)</SelectItem>
                  <SelectItem value="USER">USER</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button className="w-full" disabled={loading || !username || !password} onClick={saveAuth}>
              Continue
            </Button>
          </CardContent>
        </Card>
      )}

      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle>3 · Lightweight discovery</CardTitle>
            <CardDescription>Phase 1 maps navigation and fields without deep crawling.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Button className="w-full" disabled={loading} onClick={startDiscovery}>
              Start discovery job
            </Button>
            <Button variant="ghost" className="w-full" onClick={() => router.push(`/workspaces/${workspaceId}`)}>
              Skip for now
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
