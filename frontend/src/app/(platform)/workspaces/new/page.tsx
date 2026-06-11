import { WorkspaceCreationWizard } from '@/components/workspace/WorkspaceCreationWizard';

export const metadata = {
  title: 'New Workspace — QAptain',
};

export default function NewWorkspacePage() {
  return (
    <div className="min-h-screen bg-zinc-950 py-12 px-4">
      <div className="max-w-2xl mx-auto mb-10">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-sm">Q</span>
          </div>
          <span className="text-white font-semibold text-lg">QAptain</span>
        </div>
        <h1 className="text-3xl font-bold text-white mb-2">Create Workspace</h1>
        <p className="text-zinc-500">
          Set up your testing workspace. QAptain will learn your application semantically
          and execute business workflows like a senior QA engineer.
        </p>
      </div>
      <WorkspaceCreationWizard />
    </div>
  );
}
