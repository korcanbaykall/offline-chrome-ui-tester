"""Cookie/consent banner kapatıcı — sade selector + heuristik."""

from __future__ import annotations

from playwright.async_api import Page


_SELECTORS = [
    '#onetrust-accept-btn-handler',
    'button#onetrust-accept-btn-handler',
    'button[aria-label*="kabul" i]',
    'button[aria-label*="accept" i]',
    'button:has-text("Tümünü Kabul Et")',
    'button:has-text("Hepsini Kabul Et")',
    'button:has-text("Kabul Et")',
    'button:has-text("Kabul")',
    'button:has-text("Accept All")',
    'button:has-text("Accept")',
    'button:has-text("I Agree")',
    'button:has-text("Anladım")',
    '[id*="cookie"][id*="accept" i]',
    '[class*="cookie"] button:has-text("Kabul")',
    '[class*="consent"] button',
]


_HEURISTIC_JS = r"""
() => {
  // Shadow DOM dahil cursor:pointer + "kabul/accept/consent" içeren elementi
  // skorla, en yüksek olanı tıkla.
  const KEYS = ['kabul', 'accept', 'agree', 'tamam', 'anladım', 'allow'];
  const KW = ['cookie','consent','gdpr','kvkk','çerez','privacy'];
  function* walk(root) {
    const stack = [root];
    while (stack.length) {
      const node = stack.pop();
      if (!node) continue;
      yield node;
      if (node.shadowRoot) stack.push(node.shadowRoot);
      const kids = node.children || node.childNodes || [];
      for (let i = 0; i < kids.length; i++) {
        if (kids[i].nodeType === 1) stack.push(kids[i]);
      }
    }
  }
  let best = null, bestScore = 0;
  for (const el of walk(document)) {
    const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    if (!r || r.width < 30 || r.height < 15) continue;
    const st = window.getComputedStyle ? window.getComputedStyle(el) : null;
    if (!st) continue;
    if (st.cursor !== 'pointer' && el.tagName !== 'BUTTON' && el.tagName !== 'A') continue;
    const txt = (el.innerText || el.textContent || '').toLowerCase().trim();
    if (!txt || txt.length > 60) continue;
    let score = 0;
    for (const k of KEYS) if (txt.includes(k)) score += 5;
    if (score === 0) continue;
    // container'ında cookie/consent geçiyor mu?
    let p = el;
    for (let i = 0; i < 6 && p; i++) {
      const id = (p.id || '').toLowerCase();
      const cls = (p.className && p.className.toString) ? p.className.toString().toLowerCase() : '';
      for (const k of KW) if (id.includes(k) || cls.includes(k)) { score += 5; break; }
      p = p.parentElement;
    }
    if (score > bestScore) { best = el; bestScore = score; }
  }
  if (best) { best.click(); return true; }
  return false;
}
"""


async def dismiss(page: Page, timeout_ms: int = 5000) -> bool:
    """Cookie banner'ı kapatmayı dene. Başarılıysa True."""
    # 1. classik selector havuzu
    for sel in _SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=300):
                await loc.click(timeout=1000)
                await page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    # 2. heuristik (Shadow DOM dahil)
    try:
        ok = await page.evaluate(_HEURISTIC_JS)
        if ok:
            await page.wait_for_timeout(400)
            return True
    except Exception:
        pass
    return False
