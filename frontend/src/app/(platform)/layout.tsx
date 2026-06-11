import { PlatformShell } from '@/components/platform/platform-shell';

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  return <PlatformShell>{children}</PlatformShell>;
}
