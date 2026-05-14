import type { Page } from 'playwright';

function clip(s: string, n: number) {
  return (s || '').replace(/\s+/g, ' ').trim().slice(0, n);
}

/**
 * Compact DOM summary for the AI runner (token-bounded).
 */
export async function gatherDomSnapshot(page: Page) {
  return page.evaluate(() => {
    const clipLocal = (s: string, n: number) => (s || '').replace(/\s+/g, ' ').trim().slice(0, n);

    const headings = Array.from(document.querySelectorAll('h1,h2,h3'))
      .map((h) => clipLocal(h.textContent || '', 100))
      .filter(Boolean)
      .slice(0, 18);

    const buttons = Array.from(document.querySelectorAll('button'))
      .map((b) => {
        const el = b as HTMLButtonElement;
        return clipLocal(el.textContent || el.getAttribute('aria-label') || el.title || '', 90);
      })
      .filter(Boolean)
      .slice(0, 45);

    const links = Array.from(document.querySelectorAll('a[href]'))
      .map((a) => clipLocal(a.textContent || a.getAttribute('aria-label') || '', 90))
      .filter((t) => t.length > 1)
      .slice(0, 45);

    const formFields = Array.from(
      document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]), textarea, select'),
    )
      .slice(0, 40)
      .map((el) => {
        const i = el as HTMLInputElement;
        let label = '';
        if (i.id) {
          const lb = document.querySelector(`label[for="${CSS.escape(i.id)}"]`);
          label = lb?.textContent?.trim() || '';
        }
        if (!label && i.labels && i.labels[0]) {
          label = i.labels[0].textContent?.trim() || '';
        }
        return {
          tag: el.tagName.toLowerCase(),
          type: i.getAttribute('type') || '',
          name: clipLocal(i.name, 70),
          id: clipLocal(i.id, 50),
          placeholder: clipLocal(i.placeholder, 90),
          ariaLabel: clipLocal(i.getAttribute('aria-label') || '', 90),
          label: clipLocal(label, 90),
        };
      });

    const roleItems = ['[role="tab"]', '[role="menuitem"]', '[role="treeitem"]', '[role="option"]', '[role="row"]']
      .flatMap((sel) => Array.from(document.querySelectorAll(sel)))
      .slice(0, 30)
      .map((el) =>
        clipLocal(el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '', 90),
      )
      .filter(Boolean);

    const tableHeaders = Array.from(document.querySelectorAll('th'))
      .map((th) => clipLocal(th.textContent || '', 70))
      .filter(Boolean)
      .slice(0, 30);

    const alerts = Array.from(document.querySelectorAll('[role="alert"], .error, .text-danger, [class*="error"]'))
      .map((el) => clipLocal(el.textContent || '', 120))
      .filter(Boolean)
      .slice(0, 8);

    return {
      url: window.location.href,
      title: document.title,
      headings,
      buttons,
      links,
      roleItems,
      tableHeaders,
      formFields,
      alerts,
    };
  });
}

export function snapshotSummaryForLog(snapshot: Awaited<ReturnType<typeof gatherDomSnapshot>>): string {
  return `DOM: url=${snapshot.url} buttons=${snapshot.buttons.length} links=${snapshot.links.length} fields=${snapshot.formFields.length}`;
}
