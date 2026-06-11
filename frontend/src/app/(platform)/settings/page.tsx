export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6 lg:p-10">
      <h1 className="text-2xl font-semibold text-white">Settings</h1>
      <p className="text-sm text-slate-400">
        Profile and tenant settings will live here. Backend configuration is controlled via the{' '}
        <code className="rounded bg-slate-800 px-1 text-violet-300">backend/.env</code> file — including
        AI provider keys, ChromaDB connection, Selenium headless mode, and execution depth limits.
      </p>
    </div>
  );
}
