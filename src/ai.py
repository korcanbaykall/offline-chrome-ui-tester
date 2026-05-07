"""AI sağlayıcı katmanı — sadece ollama (lokal).

OFFLINE GARANTİSİ: Bu dosya hiçbir harici API'ye bağlanmaz. Ollama lokal
makinede çalışır, sayfa içeriği ve knowledge.md hiçbir koşulda dışarı
gönderilmez. Banka/şirket içi kullanım için tasarlandı.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass
class AIConfig:
    model: str  # ör. "llama3.1:8b"


def load_knowledge(path: str = "knowledge.md") -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def chat(cfg: AIConfig, system: str, user: str, want_json: bool = False) -> str:
    """Tek tur AI çağrısı (lokal ollama). JSON istersen want_json=True ver."""
    import ollama
    if want_json:
        system = system + "\n\nÖNEMLİ: SADECE geçerli JSON döndür. Başka açıklama veya markdown ekleme. JSON dışı tek karakter olmasın."
    # num_ctx: büyük element listeleri için context'i genişlet (default 4096
    # küçük sayfa kabuğunda bile taşıyor). 16384 RAM'e dostça ve banka login
    # gibi 50+ elementli sayfalar için yeterli.
    options = {"temperature": 0.2, "num_ctx": 16384}
    kwargs = {}
    if want_json:
        kwargs["format"] = "json"
    resp = ollama.chat(
        model=cfg.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        options=options,
        **kwargs,
    )
    return resp["message"]["content"].strip()


def parse_json(raw: str) -> dict | list:
    """AI bazen markdown fence ekler — temizleyip parse et."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
        if s.startswith("json"):
            s = s[4:].strip()
    return json.loads(s)
