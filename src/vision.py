"""Vision modeli ile sayfa ekran görüntüsünü "okuma" — DOM kazısının
yakalayamadığı görsel hata mesajlarını yakalar.

Pipeline'ın 'göz' uzmanı. Llama 3.2 Vision 11B ile.
"""

from __future__ import annotations

import base64
from typing import Any

from playwright.async_api import Page

from src.ai import chat, parse_json


async def find_error_message(
    page: Page,
    model: str,
    field_label: str = "",
) -> dict[str, Any]:
    """Sayfanın ekran görüntüsünü çek, vision modeline sor: bu input'un
    yakınında bir hata mesajı var mı? Varsa metni nedir?

    Geri dönüş: {"has_error": bool, "message": str}
    """
    try:
        img_bytes = await page.screenshot(full_page=False, type="png")
    except Exception as e:
        return {"has_error": False, "message": "", "_error": f"screenshot: {e}"}

    b64 = base64.b64encode(img_bytes).decode()

    hint = f' "{field_label}" alanı' if field_label else " bir input alanı"
    user_text = (
        f"Bu sayfanın ekran görüntüsüne bak.{hint} ile ilgili "
        "bir hata mesajı, uyarı yazısı veya kırmızı/turuncu renkli "
        "validation mesajı görüyor musun? "
        "Genellikle input'un altında veya yanında küçük bir yazı olur "
        "(örnek: 'Please enter a valid phone number', 'Lütfen geçerli...'). "
        "Sadece görsel olarak gözlemle, varsayım yapma.\n\n"
        'JSON döndür: {"has_error": true|false, "message": "tam metin veya boş"}'
    )

    try:
        raw = chat(
            model=model,
            system=(
                "Sen bir UI doğruluğu denetleyicisin. Ekran görüntüsünden "
                "form hata mesajlarını okur, JSON ile rapor edersin."
            ),
            user=user_text,
            want_json=True,
            images=[b64],
            keep_alive=0,
        )
    except Exception as e:
        return {"has_error": False, "message": "", "_error": f"vision: {e}"}

    try:
        result = parse_json(raw)
        if isinstance(result, dict):
            return {
                "has_error": bool(result.get("has_error")),
                "message": str(result.get("message", ""))[:300],
            }
    except Exception:
        pass
    return {"has_error": False, "message": "", "_raw": raw[:200]}
