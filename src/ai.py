"""AI sağlayıcı katmanı — sadece ollama (lokal). Multi-model pipeline destekli.

OFFLINE GARANTİSİ: Bu dosya hiçbir harici API'ye bağlanmaz. Ollama lokal
makinede çalışır, sayfa içeriği ve knowledge.md hiçbir koşulda dışarı
gönderilmez.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class PipelineConfig:
    """Pipeline'da kullanılacak 3 model. Her biri ayrı uzman."""
    text_model: str = "qwen3:32b"           # sayfa anlama, JSON karar
    vision_model: str = "llama3.2-vision:11b"  # ekran görüntüsü okuma
    reasoning_model: str = "deepseek-r1:32b"   # final sentez, bug hipotezi


def load_knowledge(path: str = "knowledge.md") -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def chat(
    model: str,
    system: str,
    user: str,
    want_json: bool = False,
    images: list[str] | None = None,
    keep_alive: Any = 0,
) -> str:
    """Lokal ollama çağrısı.
    images: base64-encoded image strings (vision modelleri için).
    keep_alive: 0 → çağrı sonrası modeli RAM'den boşalt (pipeline'da bir sonraki
                model sığsın diye).
    """
    import ollama

    if want_json:
        system = system + (
            "\n\nÖNEMLİ: SADECE geçerli JSON döndür. Başka açıklama veya "
            "markdown ekleme. JSON dışı tek karakter olmasın."
        )
    options = {"temperature": 0.2, "num_ctx": 16384}
    kwargs: dict[str, Any] = {"keep_alive": keep_alive}
    if want_json:
        kwargs["format"] = "json"

    user_msg: dict[str, Any] = {"role": "user", "content": user}
    if images:
        user_msg["images"] = images

    resp = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system},
            user_msg,
        ],
        options=options,
        **kwargs,
    )
    return resp["message"]["content"].strip()


def parse_json(raw: str) -> dict | list:
    """AI bazen markdown fence ekler — temizleyip parse et. Reasoning model
    çıktısındaki <think>...</think> blokları da çıkarılır."""
    s = raw.strip()
    # reasoning modelleri (DeepSeek R1, QwQ) <think>...</think> ile döndürür
    if "<think>" in s and "</think>" in s:
        s = s.split("</think>", 1)[1].strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
        if s.startswith("json"):
            s = s[4:].strip()
    return json.loads(s)


def strip_thinking(raw: str) -> str:
    """Reasoning modelinin <think>...</think> blokunu çıkar, kalan metni döndür."""
    if "<think>" in raw and "</think>" in raw:
        return raw.split("</think>", 1)[1].strip()
    return raw.strip()
