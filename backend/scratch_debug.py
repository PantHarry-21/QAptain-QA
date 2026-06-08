import asyncio
from playwright.async_api import async_playwright
import os

async def main():
    html_path = "file:///Users/harry/.gemini/antigravity-ide/brain/401b3f56-e33c-4de6-8011-6771115e18d4/artifacts/nav_debug.html"
    
    script = """
    (function() {
        const logs = [];
        function log(msg) { logs.push(msg); }
        
        function isVisible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            // for debugging, just return true so we see what's happening
            // but log if it would have been hidden
            const vis = r.width > 0 && r.height > 0
                && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            if (!vis) log('Hidden: ' + el.tagName + ' ' + el.className);
            return vis;
        }
        function getDirectText(el) {
            let t = '';
            for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
            t = t.trim().replace(/\\s+/g, ' ');
            if (!t) t = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\\s+/g, ' ');
            return t.slice(0, 80);
        }
        const NOISE = new Set(['logout','log out','sign out','notifications','help','about','profile','account','settings']);
        const NAV_SELS = ['nav', '[role="navigation"]', 'aside', '[role="menubar"]',
                          '[class*="sidebar" i]', '[class*="sider" i]', '[class*="menu-bar" i]'];
        let bestRoot = null;
        let maxItems = 0;
        for (const sel of NAV_SELS) {
            for (const el of document.querySelectorAll(sel)) {
                if (isVisible(el)) {
                    const items = el.querySelectorAll('a, button, li, [role="menuitem"], mat-list-item, .nav-item, .menu-item').length;
                    if (items > maxItems && items >= 3) {
                        maxItems = items;
                        bestRoot = el;
                    }
                }
            }
        }
        let root = bestRoot || document.body;
        log('Root element: ' + root.tagName + ' class: ' + root.className);

        const results = [];
        const seen = new Set();

        function isSubMenuItem(el) {
            let p = el.parentElement;
            while (p && p !== root) {
                const cls = (p.className || '').toLowerCase();
                const id = (p.id || '').toLowerCase();
                const role = (p.getAttribute('role') || '').toLowerCase();
                if (cls.includes('submenu') || cls.includes('sub-menu') || cls.includes('nested') ||
                    cls.includes('dropdown-menu') || cls.includes('accordion-body') || 
                    cls.includes('accordion-content') || id.includes('submenu') || 
                    role === 'group' || role === 'menu') {
                    return true;
                }
                p = p.parentElement;
            }
            return false;
        }

        const candidates = root.querySelectorAll('button, a, [role="button"], [role="menuitem"], [role="link"], [role="tab"], mat-list-item, .nav-item, .menu-item, div.text-sm');
        log('Found ' + candidates.length + ' candidates in root');
        
        for (const el of candidates) {
            if (!isVisible(el)) continue;
            const text = getDirectText(el);
            log('Eval ' + el.tagName + ' text: "' + text + '"');
            if (!text || text.length < 2 || NOISE.has(text.toLowerCase())) {
                log('  -> Rejected (noise/empty)');
                continue;
            }
            if (isSubMenuItem(el)) {
                log('  -> Rejected (isSubMenuItem)');
                continue;
            }
            if (seen.has(text.toLowerCase())) {
                log('  -> Rejected (seen)');
                continue;
            }
            seen.add(text.toLowerCase());

            const hasExpander = el.hasAttribute('aria-expanded') ||
                                el.hasAttribute('aria-haspopup') ||
                                el.classList.contains('accordion-toggle') ||
                                !!el.querySelector('[aria-expanded]') ||
                                (el.nextElementSibling && el.nextElementSibling.querySelectorAll('a, button, li, [role="menuitem"], mat-list-item, .nav-item, .menu-item, div.text-sm').length > 0) ||
                                (el.parentElement && el.parentElement.nextElementSibling && el.parentElement.nextElementSibling.querySelectorAll('a, button, li, [role="menuitem"], mat-list-item, .nav-item, .menu-item, div.text-sm').length > 0);

            results.push({
                text: text,
                is_accordion: !!hasExpander,
                tag: el.tagName.toLowerCase(),
                href: el.getAttribute('href') || ''
            });
            log('  -> ACCEPTED');
        }
        return { logs: logs, results: results };
    })()
    """
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(html_path)
        out = await page.evaluate(script)
        for line in out['logs']:
            print(line)
        print("RESULTS:", len(out['results']))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
