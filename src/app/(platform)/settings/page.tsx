export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6 lg:p-10">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <p className="text-sm text-muted-foreground">
        Profile and tenant settings will live here. Execution defaults (video recording, discovery depth) are controlled
        via environment variables such as <code className="rounded bg-muted px-1">RECORD_PLAYWRIGHT_VIDEO</code>,{' '}
        <code className="rounded bg-muted px-1">QAPTAIN_DISCOVERY_MAX_NAV</code>, and{' '}
        <code className="rounded bg-muted px-1">NEXT_PUBLIC_SUPABASE_URL</code>.
      </p>
    </div>
  );
}
