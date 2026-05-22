'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { workspaces as workspaceApi, type ExploreMode } from '@/lib/api';

type WizardStep = 'workspace' | 'application' | 'credentials' | 'explore' | 'done';

interface FormData {
  // Workspace
  workspaceName: string;
  // Application
  appName: string;
  appUrl: string;
  appDescription: string;
  // Credentials
  username: string;
  password: string;
  environmentName: string;
  // Explore
  exploreMode: ExploreMode;
}

const STEP_ORDER: WizardStep[] = ['workspace', 'application', 'credentials', 'explore'];

const EXPLORE_OPTIONS: Array<{
  mode: ExploreMode;
  title: string;
  description: string;
  duration: string;
  badge: string;
  icon: string;
}> = [
  {
    mode: 'FULL',
    title: 'Full Explore',
    description: 'Deep application exploration. Maps all modules, pages, forms, tables, and workflows. AI builds a comprehensive knowledge graph.',
    duration: '15–45 minutes',
    badge: 'Recommended',
    icon: '🔍',
  },
  {
    mode: 'SMART',
    title: 'Smart Explore',
    description: 'Main modules and major workflows only. Faster onboarding with good coverage for most enterprise applications.',
    duration: '5–15 minutes',
    badge: 'Fast',
    icon: '⚡',
  },
  {
    mode: 'SKIP',
    title: 'Skip Explore',
    description: 'No pre-exploration. AI reasons semantically at runtime. Fastest onboarding — ideal if you already know the workflows.',
    duration: 'Instant',
    badge: 'Advanced',
    icon: '🎯',
  },
];

export function WorkspaceCreationWizard() {
  const router = useRouter();
  const [step, setStep] = useState<WizardStep>('workspace');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdWorkspaceId, setCreatedWorkspaceId] = useState<string | null>(null);
  const [createdAppId, setCreatedAppId] = useState<string | null>(null);

  const [form, setForm] = useState<FormData>({
    workspaceName: '',
    appName: '',
    appUrl: '',
    appDescription: '',
    username: '',
    password: '',
    environmentName: 'Default',
    exploreMode: 'SMART',
  });

  const update = (key: keyof FormData, value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const currentStepIndex = STEP_ORDER.indexOf(step);

  const goNext = async () => {
    setError(null);

    if (step === 'workspace') {
      if (!form.workspaceName.trim()) {
        setError('Workspace name is required');
        return;
      }
      setLoading(true);
      try {
        const ws = await workspaceApi.create({ name: form.workspaceName });
        setCreatedWorkspaceId(ws.id);
        setStep('application');
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to create workspace');
      } finally {
        setLoading(false);
      }
      return;
    }

    if (step === 'application') {
      if (!form.appName.trim() || !form.appUrl.trim()) {
        setError('Application name and URL are required');
        return;
      }
      if (!form.appUrl.startsWith('http')) {
        setError('URL must start with http:// or https://');
        return;
      }
      if (form.appDescription.trim().length < 10) {
        setError('Please provide a meaningful application description (at least 10 characters). This guides AI understanding.');
        return;
      }
      setStep('credentials');
      return;
    }

    if (step === 'credentials') {
      if (!form.username.trim() || !form.password.trim()) {
        setError('Username and password are required');
        return;
      }
      setStep('explore');
      return;
    }

    if (step === 'explore') {
      setLoading(true);
      try {
        const app = await workspaceApi.createApplication(createdWorkspaceId!, {
          workspace_id: createdWorkspaceId!,
          name: form.appName,
          base_url: form.appUrl,
          description: form.appDescription,
          username: form.username,
          password: form.password,
          environment_name: form.environmentName,
          explore_mode: form.exploreMode,
        });
        setCreatedAppId(app.id);
        setStep('done');

        // Redirect to workspace with explore if not skipping
        setTimeout(() => {
          router.push(`/workspaces/${createdWorkspaceId}?app=${app.id}&explore=${form.exploreMode !== 'SKIP'}`);
        }, 1500);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to create application');
      } finally {
        setLoading(false);
      }
    }
  };

  const goBack = () => {
    const prev = STEP_ORDER[currentStepIndex - 1];
    if (prev) setStep(prev);
  };

  if (step === 'done') {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="w-16 h-16 bg-green-500 rounded-full flex items-center justify-center mb-6">
          <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h2 className="text-2xl font-semibold text-white mb-2">Workspace Created</h2>
        <p className="text-zinc-400">Setting up your application workspace...</p>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      {/* Progress */}
      <div className="flex items-center mb-10">
        {STEP_ORDER.map((s, idx) => (
          <div key={s} className="flex items-center">
            <div className={`
              flex items-center justify-center w-8 h-8 rounded-full text-sm font-medium transition-colors
              ${idx < currentStepIndex ? 'bg-blue-500 text-white' :
                idx === currentStepIndex ? 'bg-blue-600 text-white ring-2 ring-blue-400' :
                'bg-zinc-800 text-zinc-500'}
            `}>
              {idx < currentStepIndex ? (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              ) : idx + 1}
            </div>
            {idx < STEP_ORDER.length - 1 && (
              <div className={`h-0.5 w-12 mx-1 transition-colors ${idx < currentStepIndex ? 'bg-blue-500' : 'bg-zinc-800'}`} />
            )}
          </div>
        ))}
      </div>

      {/* Step Content */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-8">
        {error && (
          <div className="mb-6 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
            {error}
          </div>
        )}

        {step === 'workspace' && (
          <StepWorkspace form={form} update={update} />
        )}
        {step === 'application' && (
          <StepApplication form={form} update={update} />
        )}
        {step === 'credentials' && (
          <StepCredentials form={form} update={update} />
        )}
        {step === 'explore' && (
          <StepExplore form={form} update={update} />
        )}

        {/* Navigation */}
        <div className="flex justify-between mt-8">
          {currentStepIndex > 0 ? (
            <button
              onClick={goBack}
              disabled={loading}
              className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors disabled:opacity-50"
            >
              Back
            </button>
          ) : <div />}

          <button
            onClick={goNext}
            disabled={loading}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {loading && (
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {step === 'explore' ? 'Create Workspace' : 'Continue'}
          </button>
        </div>
      </div>
    </div>
  );
}

function StepWorkspace({ form, update }: { form: FormData; update: (k: keyof FormData, v: string) => void }) {
  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-1">Create Workspace</h2>
      <p className="text-zinc-500 text-sm mb-6">A workspace contains your applications, scenarios, and test history.</p>

      <label className="block">
        <span className="text-sm font-medium text-zinc-300 mb-1.5 block">Workspace Name</span>
        <input
          type="text"
          value={form.workspaceName}
          onChange={(e) => update('workspaceName', e.target.value)}
          placeholder="e.g. Arbro LIMS, ERP Testing, My Project"
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          autoFocus
        />
      </label>
    </div>
  );
}

function StepApplication({ form, update }: { form: FormData; update: (k: keyof FormData, v: string) => void }) {
  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-1">Application Details</h2>
      <p className="text-zinc-500 text-sm mb-6">Tell QAptain about the application it will learn and test.</p>

      <div className="space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-zinc-300 mb-1.5 block">Application Name</span>
          <input
            type="text"
            value={form.appName}
            onChange={(e) => update('appName', e.target.value)}
            placeholder="e.g. Inventory Management System"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-zinc-300 mb-1.5 block">Application URL</span>
          <input
            type="url"
            value={form.appUrl}
            onChange={(e) => update('appUrl', e.target.value)}
            placeholder="https://app.example.com"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-zinc-300 mb-1.5 block">
            Application Description
            <span className="ml-2 text-xs text-blue-400 font-normal">Guides AI understanding</span>
          </span>
          <textarea
            value={form.appDescription}
            onChange={(e) => update('appDescription', e.target.value)}
            rows={6}
            placeholder={`Describe what this application does and its key modules.

Example:
This is a laboratory management system (LIMS).

The application contains:
- Sample management (create, track, dispose samples)
- Product catalog (CRUD operations)
- Approval workflows (sample approvals, QC review)
- User and role management
- Reports and dashboards

After login, a location selection dropdown appears dynamically.
Focus on CRUD workflows, approval flows, and table operations.`}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm resize-none font-mono text-xs leading-relaxed"
          />
          <p className="mt-1 text-xs text-zinc-500">
            This description tells the AI what modules to look for, what workflows matter, and how to understand the application semantically.
          </p>
        </label>
      </div>
    </div>
  );
}

function StepCredentials({ form, update }: { form: FormData; update: (k: keyof FormData, v: string) => void }) {
  const [showPassword, setShowPassword] = useState(false);

  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-1">Authentication</h2>
      <p className="text-zinc-500 text-sm mb-6">Credentials used for exploration and test execution. Stored encrypted.</p>

      <div className="space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-zinc-300 mb-1.5 block">Username / Email</span>
          <input
            type="text"
            value={form.username}
            onChange={(e) => update('username', e.target.value)}
            placeholder="admin@example.com"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            autoComplete="off"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-zinc-300 mb-1.5 block">Password</span>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={form.password}
              onChange={(e) => update('password', e.target.value)}
              placeholder="••••••••"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm pr-10"
              autoComplete="new-password"
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
            >
              {showPassword ? '🙈' : '👁'}
            </button>
          </div>
        </label>

        <label className="block">
          <span className="text-sm font-medium text-zinc-300 mb-1.5 block">Environment Name</span>
          <input
            type="text"
            value={form.environmentName}
            onChange={(e) => update('environmentName', e.target.value)}
            placeholder="Staging"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          />
        </label>
      </div>

      <div className="mt-4 p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg">
        <p className="text-xs text-blue-300">
          Credentials are encrypted using Fernet symmetric encryption before storage. They are only decrypted in-memory during exploration and execution.
        </p>
      </div>
    </div>
  );
}

function StepExplore({ form, update }: { form: FormData; update: (k: keyof FormData, v: string) => void }) {
  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-1">Exploration Mode</h2>
      <p className="text-zinc-500 text-sm mb-6">
        Choose how QAptain learns your application before running tests.
        You can always run exploration later.
      </p>

      <div className="space-y-3">
        {EXPLORE_OPTIONS.map((opt) => (
          <button
            key={opt.mode}
            type="button"
            onClick={() => update('exploreMode', opt.mode)}
            className={`
              w-full text-left p-4 rounded-lg border transition-all
              ${form.exploreMode === opt.mode
                ? 'border-blue-500 bg-blue-500/10 ring-1 ring-blue-500'
                : 'border-zinc-800 bg-zinc-800/50 hover:border-zinc-700'}
            `}
          >
            <div className="flex items-start justify-between mb-1">
              <div className="flex items-center gap-2">
                <span>{opt.icon}</span>
                <span className="font-medium text-white text-sm">{opt.title}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  opt.badge === 'Recommended' ? 'bg-blue-500/20 text-blue-300' :
                  opt.badge === 'Fast' ? 'bg-green-500/20 text-green-300' :
                  'bg-zinc-700 text-zinc-400'
                }`}>
                  {opt.badge}
                </span>
              </div>
              <span className="text-xs text-zinc-500">{opt.duration}</span>
            </div>
            <p className="text-xs text-zinc-400 ml-6">{opt.description}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
