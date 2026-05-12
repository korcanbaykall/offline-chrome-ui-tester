"""Input test motoru — sade akış: yaz, blur, native check, gerekirse vision'a sor.

Felsefe: "her sayfa için tek tek kural yazma yerine vision modeline güven."

3 deterministik kontrol Python'da kalır (HTML5 native validity, aria-invalid,
input_rejected). Bunlar bulamazsa Continue/Submit'e basıp ekran görüntüsünü
vision modeline veririz — "ekrandaki hata mesajını oku" der. Tek karar noktası.

Eski karmaşık katmanlar (KEYWORDS havuzu, before/after diff, page-alert
absolute scan, parent ERR_SEL tarama) kaldırıldı — race condition ve
tutarsızlık üretiyorlardı.
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
  try {
    const proto = Object.getPrototypeOf(el);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, ''); else el.value = '';
  } catch (_) { el.value = ''; }
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}
"""


# Sade hata UI sondası: HTML5 native validity + aria-invalid + aria-errormessage.
# Class scan, KEYWORDS, diff yok — onlar vision'a bırakıldı.
_NATIVE_PROBE_JS = r"""
(tid) => {
  const el = document.querySelector(`[data-uitester-id="${tid}"]`);
  if (!el) return { found: false };
  if (el.validity && !el.validity.valid) {
    return { found: true, source: 'native', msg: el.validationMessage || 'invalid' };
  }
  if (el.getAttribute('aria-invalid') === 'true') {
    return { found: true, source: 'aria-invalid', msg: 'aria-invalid=true' };
  }
  const ariaIds = (el.getAttribute('aria-errormessage') || '').trim();
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
  return { found: false };
}
"""


# Submit/Continue butonunu bulup tıkla (probe etmez — sonucu vision karar verir).
_FIND_SUBMIT_JS = r"""
(s) => {
  const el = document.querySelector(s);
  if (!el) return false;
  const form = el.closest('form');
  let btn = null;
  if (form) {
    btn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!btn) btn = form.querySelector('button:not([type]), button[type=""]');
  }
  if (!btn) {
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


async def _native_probe(page: Page, tid: str) -> dict[str, Any]:
    return await page.evaluate(_NATIVE_PROBE_JS, tid)


async def _click_submit(page: Page, tid: str) -> bool:
    """Form submit butonunu bul, tıkla. Sonuç değerlendirmesi vision'a kalır.
    Click sonrası mesajın render olması için yeterli süre bekler (race
    condition'ı önlemek için)."""
    try:
        found = await page.evaluate(_FIND_SUBMIT_JS, f'[data-uitester-id="{tid}"]')
    except Exception:
        return False
    if not found:
        return False
    try:
        await page.locator('[data-uitester-submit-tmp="1"]').first.click(timeout=2000)
        # Mesajın render olması için 1.8sn bekle (animasyon + DOM update + render)
        await page.wait_for_timeout(1800)
    except Exception:
        pass
    finally:
        try:
            await page.evaluate(
                "() => document.querySelectorAll('[data-uitester-submit-tmp]').forEach(e => e.removeAttribute('data-uitester-submit-tmp'))"
            )
        except Exception:
            pass
    return True


async def _try_value(page: Page, tid: str, value: str) -> dict[str, Any]:
    """Tek bir değeri input'a yaz, blur et, sade native kontrolü oku ve gerçek
    son değeri al."""
    sel = f'[data-uitester-id="{tid}"]'
    try:
        loc = page.locator(sel)
        await loc.scroll_into_view_if_needed(timeout=2000)
        # 1) Playwright fill("") + 2) JS ile zorla temizle
        try:
            await loc.fill("")
        except Exception:
            pass
        try:
            await page.evaluate(_HARD_CLEAR_JS, sel)
        except Exception:
            pass
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
        err = await _native_probe(page, tid)
        actual = await page.evaluate(
            "(s) => { const el = document.querySelector(s); return el ? (el.value ?? '') : null; }", sel
        )
        return {"value": value, "actual_value": actual, "error": err}
    except Exception as e:
        return {"value": value, "actual_value": None, "error": {"found": False},
                "exception": f"{type(e).__name__}: {e}"}


async def test_inputs(
    page: Page,
    annotated: list[dict[str, Any]],
    vision_model: str | None = None,
) -> list[dict[str, Any]]:
    """Her input için geçerli + geçersiz değerleri dene.

    Karar:
      - Geçerli değer için: native check hata DEMEMELI + input_rejected olmamalı → PASS
      - Geçersiz değer için: native check hata DEMELİ veya input_rejected → PASS
        Yoksa submit'e bas, vision'a sor: "ekranda hata mesajı var mı?"
        Vision "var" derse → PASS, "yok" derse → FAIL (gerçekten validation eksik)
    """
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
            input_rejected = (actual is not None and _clean(actual) != _clean(v))
            r["pass"] = not (err_found or input_rejected)
            r["input_rejected"] = input_rejected
            if not r["pass"]:
                verdict_pass = False
                if input_rejected:
                    notes.append(f"Geçerli değer '{v}' yazılamadı (gerçek: '{actual}')")
                else:
                    notes.append(f"Geçerli değer '{v}' reddedildi: {r['error'].get('msg','')[:80]}")
            runs.append(r)

        for v in invalid:
            print(f"    → geçersiz '{v}'...", flush=True)
            r = await _try_value(page, el["id"], v)
            r["expected"] = "reddet"
            err_found = r["error"].get("found")
            actual = r.get("actual_value")
            input_rejected = (actual is not None and _clean(actual) != _clean(v))

            # Native ve input_rejected hata göstermediyse: submit'e bas, vision'a sor.
            # _click_submit zaten 1.8sn bekliyor — tek deneme yeterli.
            if not (err_found or input_rejected) and vision_model:
                print(f"      submit'e basıyorum → vision'a soracağım...", flush=True)
                await _click_submit(page, el["id"])
                try:
                    from src.vision import find_error_message
                    vis = await find_error_message(page, vision_model, field_label=el.get("label", ""))
                    if vis.get("has_error"):
                        r["error"] = {"found": True, "source": "vision",
                                      "msg": vis.get("message", "")}
                        r["validates_on_submit"] = True
                        err_found = True
                        print(f"      → vision yakaladı: {vis.get('message','')[:80]}", flush=True)
                    else:
                        print(f"      → vision: ekranda hata yok", flush=True)
                except Exception as e:
                    print(f"      vision çağrısı başarısız: {e}", flush=True)

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
