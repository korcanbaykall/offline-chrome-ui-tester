"""Sade HTML rapor — ✓/✗ + tek cümle özet. Eksik kalan AI yorumu opsiyonel."""

from __future__ import annotations

import datetime as _dt
import html as _html
from typing import Any


_VERDICT_BADGE = {
    "pass":         ('#22c55e', '✓ BAŞARILI'),
    "fail":         ('#ef4444', '✗ BAŞARISIZ'),
    "info":         ('#3b82f6', 'ℹ MESAJ'),
    "inconclusive": ('#a3a3a3', '? BELİRSİZ'),
}


def _badge(verdict: str) -> str:
    color, text = _VERDICT_BADGE.get(verdict, _VERDICT_BADGE["inconclusive"])
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600">{text}</span>'


def _input_badge(p: bool) -> str:
    return _badge("pass" if p else "fail")


def _esc(s: Any) -> str:
    return _html.escape(str(s) if s is not None else "")


def write_report(
    out_path: str,
    page_url: str,
    page_purpose: str,
    input_results: list[dict[str, Any]],
    button_results: list[dict[str, Any]],
    ai_summary: str = "",
) -> None:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    parts: list[str] = []
    parts.append("<!doctype html><html lang='tr'><head><meta charset='utf-8'>")
    parts.append("<title>UI Test Raporu</title>")
    parts.append("""
<style>
  body { font: 14px/1.5 -apple-system, sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 16px; color: #111; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  h2 { font-size: 17px; margin-top: 28px; border-bottom: 1px solid #e5e5e5; padding-bottom: 4px; }
  .meta { color: #666; font-size: 12px; margin-bottom: 18px; }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; vertical-align: top; }
  th { background: #fafafa; font-weight: 600; }
  code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; font-size: 12px; }
  .runs { font-size: 12px; color: #555; margin-top: 6px; }
  .runs li { margin: 2px 0; }
  .summary { background: #f9fafb; border-left: 3px solid #6366f1; padding: 10px 14px; margin: 12px 0; }
  .skip { color: #999; }
</style></head><body>
""")

    parts.append(f"<h1>UI Test Raporu</h1>")
    parts.append(f"<div class='meta'>{_esc(page_url)} — {now}</div>")
    parts.append(f"<div class='summary'><b>Sayfa amacı:</b> {_esc(page_purpose)}</div>")

    if ai_summary:
        parts.append(f"<div class='summary'><b>AI özet:</b><br>{_esc(ai_summary)}</div>")

    # buton sonuçları
    parts.append("<h2>Buton Sonuçları</h2>")
    btns = [r for r in button_results if not r.get("skipped")]
    skipped_btns = [r for r in button_results if r.get("skipped")]
    if not btns:
        parts.append("<p class='skip'>(Test edilen buton yok.)</p>")
    else:
        parts.append("<table><thead><tr><th>Buton</th><th>Beklenen Aksiyon</th><th>Sonuç</th><th>Not</th></tr></thead><tbody>")
        for r in btns:
            parts.append(
                f"<tr>"
                f"<td><code>{_esc(r.get('id'))}</code> {_esc(r.get('label') or r.get('text') or '')}</td>"
                f"<td>{_esc(r.get('expected_action', '—'))}</td>"
                f"<td>{_badge(r.get('verdict', 'inconclusive'))}</td>"
                f"<td>{_esc(r.get('note', ''))}</td>"
                f"</tr>"
            )
        parts.append("</tbody></table>")
    if skipped_btns:
        parts.append(f"<p class='skip'>Atlanan buton: {len(skipped_btns)} (navigasyon link'leri).</p>")

    # input sonuçları
    parts.append("<h2>Input Sonuçları</h2>")
    inps = [r for r in input_results if not r.get("skipped")]
    if not inps:
        parts.append("<p class='skip'>(Test edilen input yok.)</p>")
    else:
        parts.append("<table><thead><tr><th>Input</th><th>Anlamı</th><th>Genel</th><th>Denenen Değerler</th></tr></thead><tbody>")
        for r in inps:
            runs_html = "<ul class='runs'>"
            for run in r.get("runs", []):
                exp = run.get("expected")
                ok = run.get("pass")
                err = run.get("error", {})
                if err.get("found"):
                    src = err.get("source", "")
                    src_label = f" [{src}]" if src else ""
                    msg = f"{err.get('msg', '')}{src_label}"
                elif run.get("input_rejected"):
                    actual = run.get("actual_value", "")
                    msg = f"input değeri filtreledi (gerçek: '{actual}')"
                else:
                    msg = "(hata UI yok)"
                runs_html += (
                    f"<li>{_input_badge(ok)} <code>{_esc(run.get('value'))}</code> "
                    f"<span style='color:#888'>(beklenti: {_esc(exp)})</span> — {_esc(msg)}</li>"
                )
            runs_html += "</ul>"
            parts.append(
                f"<tr>"
                f"<td><code>{_esc(r.get('id'))}</code> {_esc(r.get('label'))}</td>"
                f"<td>{_esc(r.get('field_meaning', '—'))}</td>"
                f"<td>{_input_badge(r.get('pass', False))}</td>"
                f"<td>{runs_html}</td>"
                f"</tr>"
            )
        parts.append("</tbody></table>")

    parts.append("</body></html>")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
