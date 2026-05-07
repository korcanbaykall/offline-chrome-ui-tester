"""Offline UI Tester — entry script.

Akış:
  1. Browser aç, URL'ye git
  2. Cookie/consent banner kapat
  3. DOM'u tara, interaktif elementlere data-uitester-id ekle
  4. AI inspect: her element için "ne yapar / nasıl test edilir"
  5. Input testi: AI'nın verdiği geçerli/geçersiz değerlerle dene
  6. Buton testi: AI'nın aksiyon dediği butonları tıkla, sonucu gözle
  7. Rapor üret

Kullanım:
  uv run python run.py --url https://example.com
  uv run python run.py --url https://example.com --model llama3.1:8b

OFFLINE GARANTİSİ: Sadece lokal ollama kullanılır. Sayfa içeriği ve şirket
bilgi tabanı (knowledge.md) makineden çıkmaz.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

from src.ai import AIConfig
from src.button_tester import test_buttons
from src.cookies import dismiss as dismiss_cookies
from src.input_tester import test_inputs
from src.inspector import annotate, get_page_overview, inspect_with_ai, tag_elements
from src.reporter import write_report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="Test edilecek sayfa URL'i")
    p.add_argument("--model", default="llama3.1:8b",
                   help="Lokal ollama modeli (varsayılan: llama3.1:8b)")
    p.add_argument("--out", default="report.html", help="Rapor dosya yolu")
    p.add_argument("--headless", action="store_true",
                   help="Browser'ı görünmez modda aç (varsayılan: görünür)")
    p.add_argument("--slow-mo", type=int, default=300,
                   help="Aksiyonlar arası gecikme (ms, varsayılan 300 — canlı izlemek için)")
    p.add_argument("--keep-session", action="store_true",
                   help="Cookie/storage temizleme")
    return p.parse_args()


async def run(args: argparse.Namespace) -> int:
    cfg = AIConfig(model=args.model)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=args.headless,
            slow_mo=args.slow_mo,
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()

        print(f"→ Açılıyor: {args.url}")
        await page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)  # SPA hidrasyonu için

        if not args.keep_session:
            try:
                await ctx.clear_cookies()
                await page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch(e){} }")
            except Exception:
                pass

        print("→ Cookie banner kapatma deneniyor...")
        if await dismiss_cookies(page):
            print("  ✓ kapatıldı")
        else:
            print("  – banner bulunamadı (sorun değil)")

        print("→ Sayfa içeriği özetleniyor...")
        overview = await get_page_overview(page)
        print(f"  başlık: {overview.get('title','')[:80]}")
        if overview.get('h1'):
            print(f"  H1: {overview['h1'][0][:80]}")

        print("→ Sayfa elementleri taranıyor...")
        elements = await tag_elements(page)
        n_in = sum(1 for e in elements if e["kind"] == "input")
        n_bt = sum(1 for e in elements if e["kind"] == "button")
        n_nav = sum(1 for e in elements if e.get("in_nav"))
        print(f"  bulundu: {n_in} input, {n_bt} buton/link (bunlardan {n_nav} adedi nav/header/footer — AI'ya gönderilmiyor)")

        print(f"→ AI inceliyor (ollama:{cfg.model}, lokal)...")
        t0 = time.time()
        inspection = await inspect_with_ai(cfg, elements, overview, page.url)
        print(f"  süre: {time.time() - t0:.1f}sn")
        if "_error" in inspection:
            print(f"  ! AI hatası: {inspection['_error']}")

        annotated = annotate(elements, inspection)

        print("→ Input testleri çalışıyor...")
        input_results = await test_inputs(page, annotated)
        print(f"  test edilen input: {sum(1 for r in input_results if not r.get('skipped'))}")

        print("→ Buton testleri çalışıyor...")
        button_results = await test_buttons(page, annotated)
        print(f"  test edilen buton: {sum(1 for r in button_results if not r.get('skipped'))}")

        out = Path(args.out).resolve()
        write_report(
            str(out),
            page_url=args.url,
            page_purpose=inspection.get("page_purpose", "(belirsiz)"),
            input_results=input_results,
            button_results=button_results,
        )
        print(f"\n✓ Rapor: {out}")

        # Raporu yeni tab'da aç, tarayıcı manuel kapatılana kadar bekle.
        try:
            report_page = await ctx.new_page()
            await report_page.goto(f"file://{out}")
        except Exception as e:
            print(f"  (rapor tab'ı açılamadı: {e})")

        print("\nTarayıcıyı kapattığınızda program sonlanır.")
        disconnected = asyncio.Event()
        browser.on("disconnected", lambda _b: disconnected.set())
        try:
            await disconnected.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        return 0


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(run(args)))
