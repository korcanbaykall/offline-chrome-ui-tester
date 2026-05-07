"""Buton test motoru — AI'nın işaretlediği butonları tıklar, önce/sonra
snapshot'ı karşılaştırır.

Karar mantığı:
  - URL değiştiyse → navigasyon, genellikle başarılı
  - Yeni alert/error mesajı belirdiyse → form validation engelledi (FAIL eğer
    AI "navigasyon bekleniyordu" dediyse, info eğer iptal/sil onay tipiyse)
  - DOM içeriği önemli ölçüde değiştiyse → içerik güncellemesi (modal vs.)
  - Hiçbir şey olmadıysa → INCONCLUSIVE
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from src.inspector import retag_and_remap


_CLOSE_SELECTORS = [
    '[aria-label*="close" i]',
    '[aria-label*="kapat" i]',
    '[aria-label*="dismiss" i]',
    'button.close',
    '.modal-close',
    '.modal__close',
    'button:has-text("✕")',
    'button:has-text("×")',
    'button:has-text("Kapat")',
    'button:has-text("Vazgeç")',
    'button:has-text("İptal")',
]


async def _try_dismiss_overlay(page) -> None:
    """Buton tıklamasından sonra açılmış olabilecek modal/overlay'i kapatmaya
    çalış: önce ESC tuşu, sonra yaygın 'close' selector'ları."""
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
    except Exception:
        pass
    for sel in _CLOSE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=150):
                await loc.click(timeout=500)
                await page.wait_for_timeout(200)
                return
        except Exception:
            continue


_INSTALL_HOOKS_JS = r"""
() => {
  if (window.__ui_evt_installed) return;
  window.__ui_evt = { submits: 0, changes: 0, change_info: '' };
  document.addEventListener('submit', () => { window.__ui_evt.submits++; }, true);
  document.addEventListener('change', (e) => {
    window.__ui_evt.changes++;
    const t = e.target;
    if (t) {
      const checked = (t.type === 'checkbox' || t.type === 'radio') ? (' checked=' + t.checked) : '';
      const val = (t.value !== undefined && t.type !== 'password') ? (' value=' + String(t.value).slice(0,40)) : '';
      window.__ui_evt.change_info = (t.tagName || '') + (t.type ? (':' + t.type) : '') + checked + val;
    }
  }, true);
  window.__ui_evt_installed = true;
}
"""

_RESET_EVT_JS = r"""
() => { if (window.__ui_evt) { window.__ui_evt.submits = 0; window.__ui_evt.changes = 0; window.__ui_evt.change_info = ''; } }
"""

_READ_EVT_JS = r"""
() => window.__ui_evt ? { submits: window.__ui_evt.submits, changes: window.__ui_evt.changes, info: window.__ui_evt.change_info } : { submits: 0, changes: 0, info: '' }
"""


_VISIBLE_ALERTS_JS = r"""
() => {
  const sel = '[role="alert"], .alert, .toast, [class*="error"], [class*="success"], [class*="notif"]';
  const els = document.querySelectorAll(sel);
  const out = [];
  for (const el of els) {
    const r = el.getBoundingClientRect();
    const st = window.getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
    if (!visible) continue;
    const t = (el.innerText || '').trim();
    if (t) out.push(t.slice(0, 200));
  }
  return out;
}
"""


async def _snapshot(page: Page) -> dict[str, Any]:
    url = page.url
    text_len = await page.evaluate("document.body ? document.body.innerText.length : 0")
    alerts = await page.evaluate(_VISIBLE_ALERTS_JS)
    return {"url": url, "text_len": text_len, "alerts": alerts}


def _diff_alerts(before: list[str], after: list[str]) -> list[str]:
    return [a for a in after if a not in before]


async def test_buttons(
    page: Page, annotated: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    page_changed = False
    # global event yakalayıcıları sayfaya kur (1 kez)
    try:
        await page.evaluate(_INSTALL_HOOKS_JS)
    except Exception:
        pass
    for el in annotated:
        if el.get("kind") != "button":
            continue
        # nav/header/footer'da olan her şey otomatik skip
        if el.get("in_nav"):
            results.append({**el, "skipped": True, "reason": "Nav/header/footer öğesi"})
            continue
        if not el.get("should_test", True):
            results.append({**el, "skipped": True, "reason": "AI test edilmesin dedi (navigasyon)"})
            continue
        # önceki bir buton sayfayı değiştirdiyse ve geri dönülemediyse — durdur
        if page_changed:
            results.append({**el, "skipped": True, "reason": "Önceki buton sayfayı değiştirdi, kalan testler atlandı"})
            continue

        # element hâlâ DOM'da var mı? Yoksa re-tag yapıp eşleştir.
        sel = f'[data-uitester-id="{el["id"]}"]'
        exists = await page.evaluate(
            "(s) => document.querySelector(s) !== null", sel
        )
        if not exists:
            print(f"  [buton {el.get('id')}] re-tag (DOM değişmiş)...", flush=True)
            await retag_and_remap(page, annotated)
            if not el.get("_alive", False):
                print(f"    → DOM'dan kayboldu, atlandı", flush=True)
                results.append({**el, "skipped": True, "reason": "Element DOM'dan kayboldu (yeniden bulunamadı)"})
                continue
            sel = f'[data-uitester-id="{el["id"]}"]'

        print(f"  [buton {el['id']}] {el.get('label','')[:40]}", flush=True)
        before = await _snapshot(page)
        try:
            await page.evaluate(_RESET_EVT_JS)
        except Exception:
            pass
        ctx = page.context
        pages_before = list(ctx.pages)
        outcome: dict[str, Any] = {"clicked": False}
        try:
            loc = page.locator(sel)
            try:
                await loc.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            print(f"    → tıklanıyor...", flush=True)
            click_strategies = [
                ("normal", lambda: loc.click(timeout=3000)),
                ("force", lambda: loc.click(timeout=2000, force=True)),
                ("js", lambda: page.evaluate("(s) => { const el = document.querySelector(s); if (el) el.click(); }", sel)),
            ]
            click_err = None
            for name, fn in click_strategies:
                try:
                    await fn()
                    outcome["clicked"] = True
                    outcome["click_strategy"] = name
                    if name != "normal":
                        print(f"    → {name} click ile başarıldı", flush=True)
                    break
                except Exception as e:
                    click_err = e
            if not outcome["clicked"]:
                raise click_err if click_err else RuntimeError("tüm click stratejileri başarısız")
            await page.wait_for_timeout(1500)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            print(f"    → sonuç alındı", flush=True)
        except Exception as e:
            outcome["exception"] = f"{type(e).__name__}: {e}"
            print(f"    → tıklanamadı: {type(e).__name__}: {str(e)[:120]}", flush=True)

        # yeni pencere/tab açıldıysa kapat (örn. OAuth popup)
        new_windows = [p for p in ctx.pages if p not in pages_before]
        if new_windows:
            outcome["new_window"] = True
            outcome["new_window_url"] = new_windows[0].url
            for p in new_windows:
                try:
                    await p.close()
                except Exception:
                    pass
            print(f"    → yeni pencere kapatıldı: {outcome['new_window_url'][:60]}", flush=True)

        after = await _snapshot(page)
        new_alerts = _diff_alerts(before["alerts"], after["alerts"])
        url_changed = before["url"] != after["url"]
        text_delta = abs(after["text_len"] - before["text_len"])
        try:
            evt = await page.evaluate(_READ_EVT_JS)
        except Exception:
            evt = {"submits": 0, "changes": 0, "info": ""}

        # karar
        if not outcome["clicked"]:
            verdict = "fail"
            note = "Tıklanamadı: " + outcome.get("exception", "bilinmeyen")
        elif outcome.get("new_window"):
            verdict = "pass"
            note = f"Yeni pencere açtı: {outcome.get('new_window_url','')[:120]}"
        elif url_changed:
            verdict = "pass"
            note = f"Sayfa yönlendirdi: {after['url']}"
        elif evt["submits"] > 0:
            verdict = "pass"
            extra = f" — yanıt mesajı: {' | '.join(new_alerts)[:120]}" if new_alerts else ""
            note = f"Form submit edildi{extra}"
        elif evt["changes"] > 0:
            verdict = "pass"
            note = f"Durum değişti: {evt['info'][:120]}"
        elif new_alerts:
            verdict = "info"
            note = "Yeni mesaj: " + " | ".join(new_alerts)[:200]
        elif text_delta > 50:
            verdict = "pass"
            note = f"Sayfa içeriği güncellendi (Δ={text_delta} karakter)"
        else:
            verdict = "inconclusive"
            note = "Görünür değişiklik yok"

        # URL değiştiyse: geri dönmeyi denesek de DOM'daki data-uitester-id
        # attribute'ları artık yok (yeni sayfa) — kalan butonları test
        # edemeyeceğiz. Bayrak set et, döngüde sonrakiler atlansın.
        if url_changed:
            page_changed = True
            try:
                await page.go_back(wait_until="domcontentloaded", timeout=5000)
                await page.wait_for_timeout(500)
            except Exception:
                pass
        else:
            # URL aynı ama tıklama bir modal/overlay açmış olabilir.
            # Sonraki butonların erişilebilir olması için kapatmayı dene.
            await _try_dismiss_overlay(page)

        results.append({
            **el,
            "skipped": False,
            "verdict": verdict,
            "note": note,
            "before": before,
            "after": after,
            "new_alerts": new_alerts,
        })

    return results
