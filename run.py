"""Offline UI Tester — pipeline mimarisi.

3 modelli akış:
  1. Qwen 3 32B (text)         → sayfa anlama, field_meaning, buton kararları
  2. Llama 3.2 Vision 11B      → input testlerinden sonra ekran görüntüsünden
                                  hata mesajı tespiti (DOM kazısının kaçırdığı)
  3. DeepSeek R1 Distill 32B   → final sentez, bug hipotezi, tester raporu

Her adım sırayla çağrılır, model RAM'den boşaltılır (keep_alive=0).
Tek seferde RAM'de 1 model olur, 32GB makinede rahat çalışır.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

from src.ai import PipelineConfig
from src.button_tester import test_buttons
from src.cookies import dismiss as dismiss_cookies
from src.input_tester import test_inputs
from src.inspector import annotate, get_page_overview, inspect_with_ai, tag_elements
from src.reasoner import synthesize as synthesize_report
from src.reporter import write_report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="Test edilecek sayfa URL'i")
    p.add_argument("--text-model", default="qwen3:32b",
                   help="Text inceleme modeli (varsayılan: qwen3:32b)")
    p.add_argument("--vision-model", default="llama3.2-vision:11b",
                   help="Vision modeli (varsayılan: llama3.2-vision:11b)")
    p.add_argument("--reasoning-model", default="deepseek-r1:32b",
                   help="Reasoning modeli (varsayılan: deepseek-r1:32b)")
    p.add_argument("--no-vision", action="store_true",
                   help="Vision adımını atla (daha hızlı)")
    p.add_argument("--no-reasoning", action="store_true",
                   help="Reasoning adımını atla (daha hızlı)")
    p.add_argument("--out", default="report.html", help="Rapor dosya yolu")
    p.add_argument("--headless", action="store_true",
                   help="Browser'ı görünmez modda aç (varsayılan: görünür)")
    p.add_argument("--slow-mo", type=int, default=300,
                   help="Aksiyonlar arası gecikme (ms, varsayılan 300)")
    p.add_argument("--keep-session", action="store_true",
                   help="Cookie/storage temizleme")
    return p.parse_args()


async def run(args: argparse.Namespace) -> int:
    cfg = PipelineConfig(
        text_model=args.text_model,
        vision_model=args.vision_model,
        reasoning_model=args.reasoning_model,
    )

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
        await page.wait_for_timeout(1500)

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
        print(f"  bulundu: {n_in} input, {n_bt} buton/link ({n_nav} nav)")

        # === ADIM 1: TEXT MODEL — sayfa anlama ===
        print(f"\n→ [1/3] Text inceleme: {cfg.text_model} ...")
        t0 = time.time()
        inspection = await inspect_with_ai(cfg.text_model, elements, overview, page.url)
        print(f"  süre: {time.time() - t0:.1f}sn")
        if "_error" in inspection:
            print(f"  ! AI hatası: {inspection['_error']}")
        annotated = annotate(elements, inspection)

        # === Input testleri (vision çağrısı içeride, her invalid değer için
        # anında screenshot okur — buton testlerinden ÖNCE, sayfa state'i
        # bozulmadan) ===
        vision = None if args.no_vision else cfg.vision_model
        print(f"\n→ [2/3] Input testleri (vision: {vision or 'kapalı'})...")
        input_results = await test_inputs(page, annotated, vision_model=vision)
        print(f"  test edilen input: {sum(1 for r in input_results if not r.get('skipped'))}")

        print("\n→ Buton testleri çalışıyor...")
        button_results = await test_buttons(page, annotated)
        print(f"  test edilen buton: {sum(1 for r in button_results if not r.get('skipped'))}")

        # === ADIM 3: REASONING MODEL — final sentez ===
        ai_summary = ""
        if not args.no_reasoning:
            print(f"\n→ [3/3] Reasoning sentez: {cfg.reasoning_model} ...")
            t0 = time.time()
            ai_summary = synthesize_report(
                cfg.reasoning_model,
                page_url=args.url,
                page_purpose=inspection.get("page_purpose", ""),
                input_results=input_results,
                button_results=button_results,
            )
            print(f"  süre: {time.time() - t0:.1f}sn")

        out = Path(args.out).resolve()
        write_report(
            str(out),
            page_url=args.url,
            page_purpose=inspection.get("page_purpose", "(belirsiz)"),
            input_results=input_results,
            button_results=button_results,
            ai_summary=ai_summary,
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
