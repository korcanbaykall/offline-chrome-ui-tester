"""Input test motoru — geçerli/geçersiz değerleri sırayla deneyip validation
çalışıyor mu kontrol eder.

Her test:
  1. input'u temizle, değeri yaz
  2. blur (focus dışına çık) — çoğu sayfa blur'da validate eder
  3. hata UI'sı var mı kontrol et:
     - HTML5 native: el.validity.valid + validationMessage
     - aria-invalid="true"
     - parent hiyerarşisinde [role="alert"] / .error / .invalid metni
  4. karar:
     - geçerli değer → hata YOKSA pass, hata VARSA fail
     - geçersiz değer → hata VARSA pass, hata YOKSA fail (validation eksik)
"""

from __future__ import annotations

import re
from typing import Any

from playwright.async_api import Page


# input maskelerinin eklediği format karakterlerini sil ki gerçek anlamlı
# karakterler kalsın. "0531234567" yazılır → "053 123 45 67" gözükür → ikisi
# de _clean sonrası "0531234567" eşitlenir.
_FORMAT_CHARS = re.compile(r"[\s\-\(\)\.\_/]+")


def _clean(s: Any) -> str:
    return _FORMAT_CHARS.sub("", str(s or ""))


_HARD_CLEAR_JS = r"""
(s) => {
  const el = document.querySelector(s);
  if (!el) return;
  // bazı maskeli input'lar fill('') ile temizlenmiyor; doğrudan value sıfırla
  // ve event'leri tetikle ki React/Vue state'i güncellesin.
  try {
    const proto = Object.getPrototypeOf(el);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, ''); else el.value = '';
  } catch (_) { el.value = ''; }
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}
"""


_PAGE_ALERTS_JS = r"""
() => {
  const sel = '[role="alert"], [role="status"], .alert, .toast, .notice, [class*="error"], [class*="invalid"], [class*="warning"], [class*="message"], [class*="helper"], [class*="hint"]';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = window.getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || st.visibility === 'hidden' || st.display === 'none') continue;
    const t = (el.innerText || '').trim();
    if (t && t.length < 300) out.push(t);
  }
  return out;
}
"""


_BEFORE_TEXT_JS = r"""
(s) => {
  const el = document.querySelector(s);
  if (!el) return '';
  // Input'un 5 atalarına kadar görünür metni topla — sonradan diff için.
  let p = el.parentElement;
  const parts = [];
  for (let i = 0; i < 5 && p; i++) {
    parts.push((p.innerText || '').trim());
    p = p.parentElement;
  }
  return parts.join('\n---\n');
}
"""


_ERROR_PROBE_JS = r"""
(payload) => {
  const tid = payload.tid;
  const beforeText = payload.beforeText || '';
  const el = document.querySelector(`[data-uitester-id="${tid}"]`);
  if (!el) return { found: false };

  // 1. native validity (HTML5)
  if (el.validity && !el.validity.valid) {
    return { found: true, source: 'native', msg: el.validationMessage || 'invalid' };
  }
  // 2. aria-invalid="true"
  if (el.getAttribute('aria-invalid') === 'true') {
    return { found: true, source: 'aria-invalid', msg: 'aria-invalid=true' };
  }
  // 3. aria-errormessage / aria-describedby — bağlanan helper'ı oku
  const ariaIds = (el.getAttribute('aria-errormessage') || el.getAttribute('aria-describedby') || '').trim();
  if (ariaIds) {
    for (const id of ariaIds.split(/\s+/)) {
      const em = document.getElementById(id);
      if (!em) continue;
      const r = em.getBoundingClientRect();
      const st = window.getComputedStyle(em);
      const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
      const t = (em.innerText || '').trim();
      if (visible && t) return { found: true, source: 'aria-link', msg: t.slice(0, 200) };
    }
  }

  // 4. Yakın container'da hata-tipi class
  const ERR_SEL = [
    '[role="alert"]', '[role="status"]',
    '.error', '.invalid', '.field-error', '.field-message', '.input-error',
    '[class*="error"]', '[class*="invalid"]', '[class*="warning"]',
    '[class*="helper"]', '[class*="message"]', '[class*="hint"]'
  ].join(', ');
  let p = el;
  for (let i = 0; i < 5 && p; i++) {
    p = p.parentElement;
    if (!p) break;
    const others = p.querySelectorAll('input, textarea, select');
    if (others.length > 1 && i > 1) break;
    const errs = p.querySelectorAll(ERR_SEL);
    for (const er of errs) {
      if (er === el) continue;
      const r = er.getBoundingClientRect();
      const st = window.getComputedStyle(er);
      const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
      if (!visible) continue;
      const txt = (er.innerText || '').trim();
      if (txt && txt.length < 300) return { found: true, source: 'dom', msg: txt.slice(0, 200) };
    }
  }

  const KEYWORDS = [
    'valid', 'invalid', 'please', 'required', 'enter a', 'must be',
    'lütfen', 'geçersiz', 'hatalı', 'hata', 'gerekli', 'doğru',
    'eksik', 'zorunlu', 'uygun değil', 'kontrol'
  ];

  // 5a. ABSOLUTE check (diff yapmadan): input'un closest form veya parent
  // zincirinde KEYWORDS içeren GÖRÜNÜR kısa metin var mı? Bu, hata mesajının
  // önceki testten kalmış olsa bile yakalanmasını sağlar.
  const form = el.closest('form') || el.parentElement;
  if (form) {
    const allEls = form.querySelectorAll('span, div, p, small, label, [role="alert"], [role="status"]');
    for (const c of allEls) {
      if (c === el) continue;
      const r = c.getBoundingClientRect();
      const st = window.getComputedStyle(c);
      const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
      if (!visible) continue;
      const t = (c.innerText || '').trim();
      if (!t || t.length > 200) continue;
      const lower = t.toLowerCase();
      for (const kw of KEYWORDS) {
        if (lower.includes(kw)) {
          return { found: true, source: 'absolute', msg: t.slice(0, 200) };
        }
      }
    }
  }

  // 5b. Before/after diff: input'un atalarında YENİ beliren kısa metni ara,
  // anahtar kelime içeriyorsa hata kabul et.
  let p2 = el.parentElement;
  for (let i = 0; i < 5 && p2; i++) {
    const cur = (p2.innerText || '').trim();
    if (cur && !beforeText.includes(cur)) {
      // bu ata daha önce var olmayan bir metin barındırıyor — gözlem
      // sadece input civarındaki kısa metinleri kontrol et
      // input'un yakınındaki kardeşlere yakın text node'ları:
      const candidates = p2.querySelectorAll('span, div, p, small, label');
      for (const c of candidates) {
        if (c === el) continue;
        const r = c.getBoundingClientRect();
        const st = window.getComputedStyle(c);
        const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
        if (!visible) continue;
        const t = (c.innerText || '').trim();
        if (!t || t.length > 200) continue;
        if (beforeText.includes(t)) continue;
        const lower = t.toLowerCase();
        for (const kw of KEYWORDS) {
          if (lower.includes(kw)) {
            return { found: true, source: 'diff', msg: t.slice(0, 200) };
          }
        }
      }
    }
    p2 = p2.parentElement;
  }

  return { found: false };
}
"""


async def _alerts_snapshot(page: Page) -> list[str]:
    try:
        return await page.evaluate(_PAGE_ALERTS_JS)
    except Exception:
        return []


def _new_alerts(before: list[str], after: list[str]) -> list[str]:
    bset = set(before)
    return [a for a in after if a not in bset]


_PAGE_KEYWORDS = (
    "please enter", "enter a valid", "must be", "is required", "is invalid",
    "lütfen", "geçersiz", "hatalı", "uygun değil", "doğru girin", "girin",
)


def _alert_has_error_keyword(alerts: list[str]) -> str | None:
    for a in alerts:
        al = a.lower()
        for kw in _PAGE_KEYWORDS:
            if kw in al:
                return a
    return None


async def _probe_error(page: Page, tid: str, before_text: str = "",
                       before_alerts: list[str] | None = None) -> dict[str, Any]:
    res = await page.evaluate(_ERROR_PROBE_JS, {"tid": tid, "beforeText": before_text})
    if res.get("found"):
        return res
    # 1) Sayfa-genel diff: yeni beliren alert var mı?
    if before_alerts is not None:
        try:
            after = await _alerts_snapshot(page)
            new = _new_alerts(before_alerts, after)
            if new:
                return {"found": True, "source": "page-alert-new", "msg": new[0][:200]}
        except Exception:
            pass
    # 2) Sayfa-genel ABSOLUTE: herhangi bir alert "please/valid/lütfen/geçersiz"
    # gibi anahtar kelime içeriyor mu? (Aynı mesaj önceki testten kalmış olsa
    # bile yakalanır.)
    try:
        cur_alerts = await _alerts_snapshot(page)
        hit = _alert_has_error_keyword(cur_alerts)
        if hit:
            return {"found": True, "source": "page-alert-absolute", "msg": hit[:200]}
    except Exception:
        pass
    return res


_FIND_SUBMIT_JS = r"""
(s) => {
  const el = document.querySelector(s);
  if (!el) return false;
  const form = el.closest('form');
  // önce form içindeki submit; yoksa sayfa içindeki ilk submit-vari buton
  let btn = null;
  if (form) {
    btn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!btn) btn = form.querySelector('button:not([type]), button[type=""]');
  }
  if (!btn) {
    // fallback: sayfada Continue/Login/Submit text'li buton
    const all = document.querySelectorAll('button, [role="button"]');
    const KW = ['continue', 'login', 'submit', 'devam', 'giriş', 'gönder', 'kaydet', 'oturum'];
    for (const b of all) {
      const r = b.getBoundingClientRect();
      if (r.width === 0) continue;
      const t = (b.innerText || b.value || '').trim().toLowerCase();
      if (KW.some(k => t.includes(k))) { btn = b; break; }
    }
  }
  if (!btn) return false;
  btn.setAttribute('data-uitester-submit-tmp', '1');
  return true;
}
"""


async def _try_submit_and_probe(
    page: Page, tid: str, before_text: str, before_alerts: list[str]
) -> dict[str, Any] | None:
    """Form submit butonunu tıkla, sayfa kuralları submit'te kontrol ediyorsa
    çıkacak hata UI'ını yakala (sayfa-geneli alert diff dahil)."""
    try:
        found = await page.evaluate(_FIND_SUBMIT_JS, f'[data-uitester-id="{tid}"]')
    except Exception:
        return None
    if not found:
        return None
    try:
        await page.locator('[data-uitester-submit-tmp="1"]').first.click(timeout=2000)
        await page.wait_for_timeout(800)
    except Exception:
        pass
    finally:
        try:
            await page.evaluate(
                "() => document.querySelectorAll('[data-uitester-submit-tmp]').forEach(e => e.removeAttribute('data-uitester-submit-tmp'))"
            )
        except Exception:
            pass
    try:
        return await _probe_error(page, tid, before_text, before_alerts)
    except Exception:
        return None


async def _try_value(page: Page, tid: str, value: str) -> dict[str, Any]:
    """Tek bir değeri input'a yaz, blur et, hata UI'sını ve input'un GERÇEK
    son değerini oku. (Sayfa pattern/maxlength/JS ile yazımı kısıtlamış olabilir.)"""
    sel = f'[data-uitester-id="{tid}"]'
    try:
        loc = page.locator(sel)
        await loc.scroll_into_view_if_needed(timeout=2000)
        # 1) Playwright fill("") + 2) JS ile zorla temizle (maskeli input'lar
        # için React/Vue state'i de sıfırlasın diye event tetikleyerek)
        try:
            await loc.fill("")
        except Exception:
            pass
        try:
            await page.evaluate(_HARD_CLEAR_JS, sel)
        except Exception:
            pass
        # yazmadan önce ata zincirindeki metni VE sayfa genelindeki tüm
        # görünür alert'leri kaydet — sonradan "yeni mesaj belirdi mi" diff'i
        # için kullanılır
        try:
            before_text = await page.evaluate(_BEFORE_TEXT_JS, sel)
        except Exception:
            before_text = ""
        before_alerts = await _alerts_snapshot(page)
        # bazı maskeli alanlar fill()'i reddedebilir; önce normal, başarısızsa
        # tuş tuş yazmayı dene (gerçek kullanıcı simülasyonu).
        try:
            await loc.fill(str(value), timeout=3000)
        except Exception:
            try:
                await loc.click(timeout=1000)
                await loc.type(str(value), delay=10, timeout=3000)
            except Exception:
                pass
        await page.evaluate(
            "(s) => { const el = document.querySelector(s); if (el) el.blur(); }", sel
        )
        await page.wait_for_timeout(400)
        err = await _probe_error(page, tid, before_text, before_alerts)
        actual = await page.evaluate(
            "(s) => { const el = document.querySelector(s); return el ? (el.value ?? '') : null; }", sel
        )
        return {"value": value, "actual_value": actual, "error": err}
    except Exception as e:
        return {"value": value, "actual_value": None, "error": {"found": False},
                "exception": f"{type(e).__name__}: {e}"}


async def test_inputs(
    page: Page, annotated: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Her input için geçerli + geçersiz değerleri dene, sonuçları topla."""
    results = []
    for el in annotated:
        if el.get("kind") != "input":
            continue
        if el.get("in_nav"):
            results.append({**el, "skipped": True, "reason": "Nav/header/footer öğesi"})
            continue
        if not el.get("should_test", True):
            results.append({**el, "skipped": True, "reason": "AI test edilmesin dedi"})
            continue

        valid = el.get("valid_values") or []
        invalid = el.get("invalid_values") or []
        runs = []
        verdict_pass = True
        notes = []

        print(f"  [input {el['id']}] {el.get('label','')[:40]} — {len(valid)} geçerli + {len(invalid)} geçersiz", flush=True)
        for v in valid:
            print(f"    → geçerli '{v}'...", flush=True)
            r = await _try_value(page, el["id"], v)
            r["expected"] = "kabul"
            err_found = r["error"].get("found")
            actual = r.get("actual_value")
            # input maske formatlama uygulayabilir (053 123 45 67 ↔ 0531234567).
            # Bunu gürültü olarak gör: ayıklanmış karşılaştırma yap.
            input_rejected = (
                actual is not None and _clean(actual) != _clean(v)
            )
            r["pass"] = not (err_found or input_rejected)
            r["input_rejected"] = input_rejected
            if not r["pass"]:
                verdict_pass = False
                if input_rejected:
                    notes.append(f"Geçerli değer '{v}' input'a yazılamadı (gerçek: '{actual}')")
                else:
                    notes.append(f"Geçerli değer '{v}' reddedildi: {r['error'].get('msg','')[:80]}")
            runs.append(r)

        for v in invalid:
            print(f"    → geçersiz '{v}'...", flush=True)
            r = await _try_value(page, el["id"], v)
            r["expected"] = "reddet"
            err_found = r["error"].get("found")
            actual = r.get("actual_value")
            input_rejected = (
                actual is not None and _clean(actual) != _clean(v)
            )
            # Sayfa validation'ı blur'da çalıştırmıyor olabilir (örn IKEA "Continue"
            # butonuna basınca kontrol ediyor). Hata yoksa submit deneyip tekrar bak.
            if not (err_found or input_rejected):
                print(f"      submit deniyorum (blur'da hata yok)...", flush=True)
                try:
                    bt = await page.evaluate(_BEFORE_TEXT_JS, f'[data-uitester-id="{el["id"]}"]')
                except Exception:
                    bt = ""
                ba = await _alerts_snapshot(page)
                submit_err = await _try_submit_and_probe(page, el["id"], bt, ba)
                if submit_err and submit_err.get("found"):
                    r["error"] = submit_err
                    r["validates_on_submit"] = True
                    err_found = True
                    print(f"      → submit'te yakaladı: {submit_err.get('msg','')[:60]}", flush=True)
            r["pass"] = bool(err_found or input_rejected)
            r["input_rejected"] = input_rejected
            if not r["pass"]:
                verdict_pass = False
                notes.append(f"Geçersiz değer '{v}' kabul edildi (validation eksik)")
            runs.append(r)

        results.append({
            **el,
            "skipped": False,
            "runs": runs,
            "pass": verdict_pass,
            "notes": notes,
        })

    return results
