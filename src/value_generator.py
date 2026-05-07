"""Field meaning + DOM attributes → (valid, invalid) test değerleri.

AI sadece field_meaning (alan ne ister) söyler. Bu modül deterministik
olarak knowledge.md kurallarına uyumlu, pattern/maxlength/min/max'a uyarlı
test değerleri üretir. Böylece AI tutarsız değer üretip testi bozmaz.

Kural: geçerli değer = tam formatlı, mantıklı, gerçek bir kullanıcı girebilir.
       geçersiz değer = format'ı geçer ama sayfa mantığına aykırı.
"""

from __future__ import annotations

from typing import Any


_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "telefon": {
        "valid": ["5551234567", "5321234567"],
        "invalid": ["0000000000", "1111111111", "9999999999"],
    },
    "phone": {
        "valid": ["5551234567", "5321234567"],
        "invalid": ["0000000000", "1111111111", "9999999999"],
    },
    "email": {
        "valid": ["test@example.com", "user@gmail.com"],
        "invalid": ["user@invalid.invalid", "test@nonexistent.test"],
    },
    "eposta": {
        "valid": ["test@example.com", "user@gmail.com"],
        "invalid": ["user@invalid.invalid", "test@nonexistent.test"],
    },
    "şifre": {
        "valid": ["Test1234!", "Password1!"],
        "invalid": ["123", "abc", "password"],
    },
    "sifre": {
        "valid": ["Test1234!", "Password1!"],
        "invalid": ["123", "abc", "password"],
    },
    "password": {
        "valid": ["Test1234!", "Password1!"],
        "invalid": ["123", "abc", "password"],
    },
    "yaş": {
        "valid": ["25", "40", "65"],
        "invalid": ["999", "200"],
    },
    "yas": {
        "valid": ["25", "40", "65"],
        "invalid": ["999", "200"],
    },
    "age": {
        "valid": ["25", "40", "65"],
        "invalid": ["999", "200"],
    },
    "tc": {
        "valid": ["10000000146"],
        "invalid": ["00000000000", "12345678901"],
    },
    "kimlik": {
        "valid": ["10000000146"],
        "invalid": ["00000000000", "12345678901"],
    },
    "tarih": {
        "valid": ["1990-01-15", "15.01.1990"],
        "invalid": ["1850-01-01", "2050-01-01"],
    },
    "date": {
        "valid": ["1990-01-15"],
        "invalid": ["1850-01-01", "2050-01-01"],
    },
    "ad": {
        "valid": ["Ahmet", "Mehmet"],
        "invalid": ["12345", "!@#"],
    },
    "isim": {
        "valid": ["Ahmet", "Mehmet"],
        "invalid": ["12345", "!@#"],
    },
    "name": {
        "valid": ["Ahmet", "John"],
        "invalid": ["12345", "!@#"],
    },
    "soyad": {
        "valid": ["Yılmaz", "Demir"],
        "invalid": ["12345", "!@#"],
    },
    "iban": {
        "valid": ["TR320010009999901234567890"],
        "invalid": ["TR12345"],
    },
    "tutar": {
        "valid": ["100", "500.50"],
        "invalid": ["-100"],
    },
    "miktar": {
        "valid": ["100", "500.50"],
        "invalid": ["-100"],
    },
    "kullanıcı": {
        "valid": ["testuser"],
        "invalid": ["a"],
    },
    "username": {
        "valid": ["testuser"],
        "invalid": ["a"],
    },
    "url": {
        "valid": ["https://example.com"],
        "invalid": ["notaurl"],
    },
    "unknown": {
        "valid": ["test123"],
        "invalid": ["!@#"],
    },
}


def _match_meaning(fm: str) -> str:
    fm = (fm or "").strip().lower()
    if not fm:
        return "unknown"
    for known in _DEFAULTS:
        if known in fm or fm in known:
            return known
    return "unknown"


def values_for(field_meaning: str, dom_attrs: dict[str, Any] | None = None
               ) -> tuple[list[str], list[str]]:
    """(valid, invalid) listeleri üret. dom_attrs: type, min, max, maxlength,
    minlength, pattern."""
    key = _match_meaning(field_meaning)
    base = _DEFAULTS[key]
    valid = list(base["valid"])
    invalid = list(base["invalid"])

    if not dom_attrs:
        return valid, invalid

    attr_type = (dom_attrs.get("type") or "").lower()

    # Sayısal alan: min/max'a göre dışına invalid değer ekle
    if attr_type in ("number", "range"):
        try:
            lo = dom_attrs.get("min")
            if lo not in (None, ""):
                invalid.insert(0, str(int(float(lo)) - 1))
        except Exception:
            pass
        try:
            hi = dom_attrs.get("max")
            if hi not in (None, ""):
                invalid.insert(0, str(int(float(hi)) + 1))
        except Exception:
            pass

    # maxlength varsa: hem geçerli hem geçersiz değerleri kırpma değil — kırpılmış
    # değer test edilemez. Bunun yerine maxlength'i aşan invalid değer ÜRETMEYELIM
    # (input zaten kabul etmez). Mevcut listeden maxlength'i aşanları çıkar.
    try:
        ml = int(dom_attrs.get("maxlength") or 0)
        if ml > 0:
            valid = [v for v in valid if len(v) <= ml]
            invalid = [v for v in invalid if len(v) <= ml]
            # boşaldıysa generic ekle
            if not valid:
                valid = ["1" * ml]
            if not invalid:
                invalid = ["0" * ml]
    except Exception:
        pass

    # minlength: çok kısa valid'leri çıkar, generic doldur
    try:
        mn = int(dom_attrs.get("minlength") or 0)
        if mn > 0:
            valid = [v for v in valid if len(v) >= mn]
            if not valid:
                valid = ["1" * mn]
    except Exception:
        pass

    return valid, invalid
