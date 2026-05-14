import type { Page } from 'playwright';

/** Raw field capture from in-page evaluation (no Node imports). */
export type RawDomField = {
  fieldKey: string;
  tag: string;
  type: string;
  name: string;
  id: string;
  placeholder: string;
  ariaLabel: string;
  required: boolean;
  minLength: number | null;
  maxLength: number | null;
  pattern: string;
  inputMode: string;
  labelText: string;
  options: string[];
  multiple?: boolean;
};

export async function extractRawFieldsFromPage(page: Page, maxFields = 120): Promise<RawDomField[]> {
  return page.evaluate((limit) => {
    const out: RawDomField[] = [];
    const seen = new Set<string>();

    function labelFor(el: Element): string {
      const id = (el as HTMLInputElement).id;
      if (id) {
        const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
        if (lab?.textContent) return lab.textContent.trim().replace(/\s+/g, ' ');
      }
      let p: Element | null = el.parentElement;
      for (let d = 0; d < 4 && p; d++, p = p.parentElement) {
        const l = p.querySelector?.(':scope > label');
        if (l?.textContent) return l.textContent.trim().replace(/\s+/g, ' ');
      }
      return '';
    }

    const els = Array.from(document.querySelectorAll('input, textarea, select'));
    for (const el of els) {
      if (out.length >= limit) break;
      const tag = el.tagName.toLowerCase();
      const inp = el as HTMLInputElement;
      const type = tag === 'input' ? (inp.type || 'text').toLowerCase() : tag;
      if (type === 'hidden' || type === 'submit' || type === 'button' || type === 'reset') continue;

      const name = inp.name || '';
      const id = inp.id || '';
      const key = name || id || `anon_${out.length}`;
      if (seen.has(key)) continue;
      seen.add(key);

      let options: string[] = [];
      let multiple = false;
      if (tag === 'select') {
        multiple = (el as HTMLSelectElement).multiple;
        options = Array.from((el as HTMLSelectElement).options)
          .map((o) => o.textContent?.trim() || '')
          .filter(Boolean)
          .slice(0, 40);
      }

      out.push({
        fieldKey: key.slice(0, 200),
        tag,
        type,
        name: name.slice(0, 200),
        id: id.slice(0, 200),
        placeholder: (inp.placeholder || '').slice(0, 300),
        ariaLabel: (inp.getAttribute('aria-label') || '').slice(0, 300),
        required: el.hasAttribute('required'),
        minLength: inp.minLength > 0 ? inp.minLength : null,
        maxLength: inp.maxLength > 0 ? inp.maxLength : null,
        pattern: (inp.pattern || '').slice(0, 500),
        inputMode: (inp.getAttribute('inputmode') || '').slice(0, 50),
        labelText: labelFor(el).slice(0, 300),
        options,
        multiple,
      });
    }
    return out;
  }, maxFields);
}
