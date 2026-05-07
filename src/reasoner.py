"""Reasoning modeli ile final sentez — test sonuçlarını okuyup
"genel sonuç + bug hipotezi" üretir.

Pipeline'ın 'dedektif' uzmanı. DeepSeek R1 Distill 32B (thinking model).
"""

from __future__ import annotations

import json
from typing import Any

from src.ai import chat, strip_thinking


def synthesize(
    model: str,
    page_url: str,
    page_purpose: str,
    input_results: list[dict[str, Any]],
    button_results: list[dict[str, Any]],
) -> str:
    """Test sonuçlarını yorumla, kısa Türkçe rapor üret."""

    inp_summary = []
    for r in input_results:
        if r.get("skipped"):
            continue
        runs = []
        for run in r.get("runs", []):
            err = run.get("error", {})
            runs.append({
                "value": run.get("value"),
                "expected": run.get("expected"),
                "passed": run.get("pass"),
                "actual": run.get("actual_value"),
                "error_message": err.get("msg", "") if err.get("found") else "",
                "error_source": err.get("source", "") if err.get("found") else "",
            })
        inp_summary.append({
            "input": r.get("label"),
            "field_meaning": r.get("field_meaning"),
            "overall_pass": r.get("pass"),
            "notes": r.get("notes", []),
            "runs": runs,
        })

    btn_summary = []
    for r in button_results:
        if r.get("skipped"):
            continue
        btn_summary.append({
            "button": r.get("label") or r.get("text", ""),
            "expected_action": r.get("expected_action", ""),
            "verdict": r.get("verdict"),
            "note": r.get("note"),
            "click_strategy": r.get("click_strategy", "normal"),
        })

    user = (
        f"Sayfa: {page_url}\n"
        f"Sayfa amacı: {page_purpose}\n\n"
        f"=== INPUT TEST SONUÇLARI ===\n"
        f"{json.dumps(inp_summary, ensure_ascii=False, indent=2)}\n\n"
        f"=== BUTON TEST SONUÇLARI ===\n"
        f"{json.dumps(btn_summary, ensure_ascii=False, indent=2)}\n\n"
        "Bu test sonuçlarını analiz et ve kıdemli bir QA mühendisi gibi "
        "kısa, NET bir Türkçe rapor yaz. Şunları cevapla:\n\n"
        "1. **Genel sonuç** (1 cümle): sayfa fonksiyonel olarak çalışıyor mu?\n"
        "2. **Gerçek bug'lar**: hangi alanlar gerçekten kırık görünüyor? "
        "(Sadece test akışı limitasyonundan kaynaklananları bug saymaktan kaçın.)\n"
        "3. **Şüpheli durumlar**: BAŞARISIZ görünüp aslında test akışı "
        "limitasyonundan kaynaklanabilecek vakalar.\n"
        "4. **Tester ekibine tavsiye**: 1-2 cümle, ne yapmalılar?\n\n"
        "Markdown başlıkları kullan ama ayrıntıya boğma. Toplam 200 kelimeyi "
        "geçmesin. Sade dil."
    )

    try:
        raw = chat(
            model=model,
            system=(
                "Sen kıdemli bir QA mühendisisin. Otomatik test sonuçlarını "
                "okur, gerçek bug'larla test akışı limitasyonlarını ayırt eder, "
                "tester ekibine kısa rapor yazarsın. Türkçe konuşursun."
            ),
            user=user,
            want_json=False,
            keep_alive=0,
        )
    except Exception as e:
        return f"(Reasoning modeli yanıtlamadı: {type(e).__name__}: {e})"

    return strip_thinking(raw)
