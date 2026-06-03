'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Plus } from 'lucide-react';
import { workspaces as workspacesApi, type Workspace } from '@/lib/api';

export default function WorkspacesPage() {
  const router = useRouter();
  const [list, setList] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [saving, setSaving] = useState(false);

  // Delete state
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmName, setConfirmName] = useState('');
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    workspacesApi.list()
      .then((data) => setList(Array.isArray(data) ? data : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const openEdit = (e: React.MouseEvent, w: Workspace) => {
    e.preventDefault();
    e.stopPropagation();
    setEditingId(w.id);
    setEditName(w.name);
    setEditDesc(w.description || '');
  };

  const saveEdit = async () => {
    if (!editingId || !editName.trim()) return;
    setSaving(true);
    try {
      const updated = await workspacesApi.update(editingId, { name: editName.trim(), description: editDesc });
      setList((prev) => prev.map((w) => w.id === editingId ? { ...w, ...updated } : w));
      setEditingId(null);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  };

  const openDelete = (e: React.MouseEvent, w: Workspace) => {
    e.preventDefault();
    e.stopPropagation();
    setDeletingId(w.id);
    setConfirmName('');
  };

  const confirmDelete = async () => {
    const ws = list.find((w) => w.id === deletingId);
    if (!ws || confirmName !== ws.name) return;
    setDeleting(true);
    try {
      await workspacesApi.delete(deletingId!);
      setList((prev) => prev.filter((w) => w.id !== deletingId));
      setDeletingId(null);
    } catch { /* ignore */ }
    finally { setDeleting(false); }
  };

  const editingWs = list.find((w) => w.id === editingId);
  const deletingWs = list.find((w) => w.id === deletingId);

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6 lg:p-10 relative z-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-white">Workspaces</h1>
          <p className="mt-1 text-slate-400">One workspace per application under test.</p>
        </div>
        <Button asChild className="gap-2 bg-violet-600 hover:bg-violet-700 text-white shadow-lg shadow-violet-600/20">
          <Link href="/workspaces/new">
            <Plus className="h-4 w-4" />
            Add workspace
          </Link>
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-slate-400 animate-pulse">Loading workspaces…</p>
      ) : list.length === 0 ? (
        <Card className="border-dashed border-slate-800 bg-slate-900/40 backdrop-blur-xl">
          <CardHeader>
            <CardTitle className="text-white">No workspaces yet</CardTitle>
            <CardDescription className="text-slate-400">
              Create your first workspace to configure a URL, credentials, and run AI exploration.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild className="bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20">
              <Link href="/workspaces/new">Create workspace</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {list.map((w) => (
            <div
              key={w.id}
              className="group relative cursor-pointer"
              onClick={() => router.push(`/workspaces/${w.id}`)}
            >
              <Card className="h-full border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-lg transition-all hover:shadow-violet-900/20 hover:border-violet-500/50 hover:-translate-y-1">
                <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
                  <div className="flex-1 min-w-0">
                    <CardTitle className="text-lg text-white group-hover:text-violet-300 transition-colors truncate">
                      {w.name}
                    </CardTitle>
                    <CardDescription className="line-clamp-2 text-slate-400">
                      {w.description || '—'}
                    </CardDescription>
                  </div>
                  {/* Action buttons — visible on hover */}
                  <div className="flex items-center gap-1 ml-2 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                       onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={(e) => openEdit(e, w)}
                      className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
                      title="Edit workspace"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>
                    <button
                      onClick={(e) => openDelete(e, w)}
                      className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                      title="Delete workspace"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="secondary" className="bg-slate-800 text-slate-300">
                      {w.application_count ?? 0} app{(w.application_count ?? 0) !== 1 ? 's' : ''}
                    </Badge>
                  </div>
                  <div>
                    <div className="mb-1 flex justify-between text-xs text-slate-400">
                      <span>Readiness</span>
                      <span className="text-violet-400 font-medium">{w.readiness ?? 0}%</span>
                    </div>
                    <Progress value={w.readiness ?? 0} className="h-2 bg-slate-800 [&>div]:bg-violet-500" />
                  </div>
                </CardContent>
              </Card>
            </div>
          ))}
        </div>
      )}

      {/* ── Edit Modal ── */}
      {editingId && editingWs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-zinc-900 border border-zinc-700 rounded-2xl p-6 shadow-2xl">
            <h2 className="text-lg font-semibold text-white mb-4">Edit Workspace</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Name</label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Description</label>
                <textarea
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  rows={3}
                  className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
                />
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button
                onClick={() => setEditingId(null)}
                className="flex-1 px-4 py-2 text-sm text-zinc-400 hover:text-white border border-zinc-700 hover:border-zinc-600 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={saving || !editName.trim()}
                className="flex-1 px-4 py-2 text-sm bg-violet-600 hover:bg-violet-500 text-white rounded-lg transition-colors disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete Confirmation Modal ── */}
      {deletingId && deletingWs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-zinc-900 border border-red-500/30 rounded-2xl p-6 shadow-2xl">
            <div className="flex items-start gap-3 mb-4">
              <div className="w-9 h-9 rounded-full bg-red-500/20 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <h2 className="text-base font-semibold text-white">Delete Workspace</h2>
                <p className="text-sm text-zinc-400 mt-0.5">
                  This will permanently delete <span className="text-white font-medium">{deletingWs.name}</span> and all its applications, scenarios, and execution history. This cannot be undone.
                </p>
              </div>
            </div>
            <div className="mb-4">
              <label className="block text-xs font-medium text-zinc-400 mb-1">
                Type <span className="text-white font-mono">{deletingWs.name}</span> to confirm
              </label>
              <input
                type="text"
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
                placeholder={deletingWs.name}
                className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                autoFocus
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => setDeletingId(null)}
                className="flex-1 px-4 py-2 text-sm text-zinc-400 hover:text-white border border-zinc-700 hover:border-zinc-600 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting || confirmName !== deletingWs.name}
                className="flex-1 px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting…' : 'Delete Workspace'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
