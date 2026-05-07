"""Sayfa inceleme — DOM'u tara, AI'ya yapılandırılmış soru sor.

Üç adım:
1. get_page_overview: sayfa başlığı, h1/h2'ler, meta description, ana içerik
   metni — AI'ya bağlam.
2. tag_elements: tüm interaktif öğeleri yakala, her birine geçici test-id ata,
   etiketlerini Python'da çıkar.
3. inspect_with_ai: overview + element listesi + knowledge.md → AI her öğe
   için ne yaptığını ve (input için) geçerli/geçersiz değerleri belirler.
"""

from __future__ import annotations

import json
from typing import Any

from playwright.async_api import Page

from src.ai import AIConfig, chat, load_knowledge, parse_json


_OVERVIEW_JS = r"""
() => {
  const title = document.title || '';
  const meta = document.querySelector('meta[name="description"]');
  const desc = meta ? (meta.getAttribute('content') || '') : '';
  const h1 = Array.from(document.querySelectorAll('h1')).slice(0, 3)
    .map(e => (e.innerText || '').trim()).filter(Boolean);
  const h2 = Array.from(document.querySelectorAll('h2')).slice(0, 6)
    .map(e => (e.innerText || '').trim()).filter(Boolean);
  // ana içerik metni — main varsa ondan, yoksa body'nin görünür metninden
  const main = document.querySelector('main') || document.body;
  const text = ((main && main.innerText) || '').replace(/\s+/g, ' ').trim().slice(0, 800);
  return { title, description: desc.slice(0, 300), h1, h2, main_text: text };
}
"""


async def get_page_overview(page) -> dict[str, Any]:
    return await page.evaluate(_OVERVIEW_JS)


# Her interaktif öğeye `data-uitester-id` ekleyen JS.
# clear_existing parametresi true ise eski attribute'ları siler ve sıfırdan başlar
# (re-tag senaryosu için).
_TAG_JS = r"""
(opts) => {
  const clearExisting = opts && opts.clearExisting;
  if (clearExisting) {
    document.querySelectorAll('[data-uitester-id]').forEach(e => e.removeAttribute('data-uitester-id'));
  }
  const sels = [
    'button', 'input', 'textarea', 'select',
    'a[href]', '[role="button"]', '[onclick]',
    '[class*="cursor-pointer"]'
  ];
  const seen = new Set();
  const out = [];
  let id = 0;
  for (const sel of sels) {
    const els = document.querySelectorAll(sel);
    for (const el of els) {
      if (seen.has(el)) continue;
      seen.add(el);
      // görünür mü?
      const r = el.getBoundingClientRect();
      const st = window.getComputedStyle(el);
      const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
      if (!visible) continue;
      // type'a göre güzel etiket çıkar
      const tag = el.tagName.toLowerCase();
      const inputType = (el.getAttribute('type') || '').toLowerCase();
      let kind = 'button';
      if (tag === 'input' && !['button','submit','reset','image','checkbox','radio'].includes(inputType)) kind = 'input';
      else if (tag === 'textarea') kind = 'input';
      else if (tag === 'select') kind = 'input';
      // nav/header/footer içinde mi?
      // Tag adı (NAV/HEADER/FOOTER) veya ARIA role → kesin nav.
      // Class match yapmıyoruz — false-positive yapıyor (login-form-header,
      // card-header gibi içerik öğeleri yanlışlıkla yakalanıyor).
      let inNav = false;
      let p = el;
      while (p && p !== document.body) {
        const t = p.tagName;
        if (t === 'NAV' || t === 'HEADER' || t === 'FOOTER') { inNav = true; break; }
        const role = (p.getAttribute && p.getAttribute('role')) || '';
        if (role === 'navigation' || role === 'banner' || role === 'contentinfo') { inNav = true; break; }
        p = p.parentElement;
      }
      // ELEMENT'in kendi ID'si "header*" / "footer*" / "nav*" ile başlıyorsa
      // (camelCase dahil — Koçtaş'taki headerToptanSatis gibi)
      if (!inNav) {
        const ownId = el.id || '';
        if (/^(header|footer|nav)[A-Z\-_]?/.test(ownId)) inNav = true;
      }
      const label =
        (el.getAttribute('aria-label') || '').trim() ||
        (el.getAttribute('placeholder') || '').trim() ||
        (el.getAttribute('name') || '').trim() ||
        (el.id || '').trim() ||
        (el.innerText || el.value || '').trim().slice(0, 80);
      // gerçek input/select/textarea için associated <label>
      let labelText = '';
      if (kind === 'input' && el.id) {
        const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (lbl) labelText = lbl.innerText.trim();
      }
      id += 1;
      const tid = 't' + id;
      el.setAttribute('data-uitester-id', tid);
      // Input için tam validation spec'i topla — pattern/min/max/maxlength
      // gibi sayfa zaten dayatıyor; AI bunları görmezse pattern'in reddettiği
      // değerleri 'invalid' olarak üretip zaman kaybeder.
      const dataAttrs = {};
      for (const a of el.attributes) {
        if (a.name.startsWith('data-') || a.name.startsWith('aria-')) {
          dataAttrs[a.name] = (a.value || '').slice(0, 80);
        }
      }
      // çevre HTML bağlamı — yardım metni / fieldset legend / form heading
      let context = '';
      if (kind === 'input') {
        const aria = el.getAttribute('aria-describedby');
        if (aria) {
          const helper = document.getElementById(aria);
          if (helper) context = (helper.innerText || '').trim().slice(0, 150);
        }
        if (!context) {
          // parent zincirinde küçük bir help metni var mı?
          let pp = el.parentElement;
          for (let i = 0; i < 3 && pp; i++) {
            const help = pp.querySelector('.help, .hint, .description, [class*="helper"], [class*="hint"]');
            if (help && help !== el) {
              const t = (help.innerText || '').trim();
              if (t && t.length < 200) { context = t; break; }
            }
            pp = pp.parentElement;
          }
        }
      }
      // outerHTML kısaltılmış (özellikle data-mask gibi şeyler için faydalı)
      const outer = (el.outerHTML || '').replace(/\s+/g, ' ').slice(0, 300);

      out.push({
        id: tid,
        kind: kind,
        tag: tag,
        type: inputType,
        label: (labelText || label || '(etiketsiz)').slice(0, 60),
        name: el.getAttribute('name') || '',
        placeholder: (el.getAttribute('placeholder') || '').slice(0, 60),
        autocomplete: el.getAttribute('autocomplete') || '',
        inputmode: el.getAttribute('inputmode') || '',
        pattern: el.getAttribute('pattern') || '',
        min: el.getAttribute('min') || '',
        max: el.getAttribute('max') || '',
        step: el.getAttribute('step') || '',
        minlength: el.getAttribute('minlength') || '',
        maxlength: el.getAttribute('maxlength') || '',
        required: el.hasAttribute('required'),
        readonly: el.hasAttribute('readonly'),
        disabled: el.hasAttribute('disabled'),
        data_attrs: dataAttrs,
        context: context,
        outer_html: outer,
        in_nav: inNav,
      });
    }
  }
  return out;
}
"""


async def tag_elements(page: Page, clear_existing: bool = False) -> list[dict[str, Any]]:
    """DOM'u tara, görünür interaktif öğelere `data-uitester-id` ekle, listeyi
    döndür. clear_existing=True ise önce eski attribute'ları siler (re-tag)."""
    return await page.evaluate(_TAG_JS, {"clearExisting": clear_existing})


def _strip_for_ai(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """AI'ya minimal liste — sadece field_meaning ve buton kararı için yeter
    olanı. Tam DOM spec Python tarafında value_generator'a gider."""
    out = []
    for e in elements:
        if e.get("in_nav"):
            continue
        if e.get("kind") == "input":
            item = {
                "id": e["id"],
                "kind": "input",
                "label": e.get("label", ""),
                "type": e.get("type", ""),
                "name": e.get("name", ""),
                "placeholder": e.get("placeholder", ""),
            }
            out.append({k: v for k, v in item.items() if v not in ("", False, None)})
        else:
            item = {
                "id": e["id"],
                "kind": "button",
                "label": e.get("label", ""),
            }
            out.append({k: v for k, v in item.items() if v not in ("", False, None)})
    return out


def _build_prompt(
    elements: list[dict[str, Any]],
    overview: dict[str, Any],
    knowledge: str,
    page_url: str,
) -> tuple[str, str]:
    system = (
        "Sen bir UI test asistanısın. İşin SADECE iki kararı vermek:\n"
        "1) Her input için 'field_meaning' (alan ne istiyor — telefon/email/yaş/şifre/"
        "tc/ad/tarih/iban/tutar/url/kullanıcı/unknown — tek kelime).\n"
        "2) Her buton için 'expected_action' (1 cümle) ve test edilmesi gerekiyor mu.\n"
        "Test DEĞERLERİ üretme — onları program kendi seçer."
    )

    slim = _strip_for_ai(elements)

    overview_block = (
        f"Başlık: {overview.get('title','')}\n"
        f"H1: {overview.get('h1', [])}\n"
        f"H2: {overview.get('h2', [])}\n"
    )

    user = (
        f"URL: {page_url}\n\n"
        f"Sayfa: {overview_block}\n"
        f"Öğeler:\n{json.dumps(slim, ensure_ascii=False)}\n\n"
        "Çıktı (sadece JSON):\n"
        "{\n"
        '  "page_purpose": "1 cümle",\n'
        '  "items": [\n'
        '    {"id":"t1","kind":"input","field_meaning":"telefon","should_test":true},\n'
        '    {"id":"t5","kind":"button","should_test":true,"expected_action":"Login formunu submit eder","is_navigation_only":false}\n'
        "  ]\n"
        "}\n\n"
        "Kurallar:\n"
        "- field_meaning seçenekleri: telefon, email, şifre, yaş, tc, ad, soyad, "
        "tarih, iban, tutar, kullanıcı, url, unknown.\n"
        "- Aksiyon butonlarını (login, submit, kaydet, sil, öde) test et.\n"
        "- Sadece nav/header link'lerini `should_test:false` + `is_navigation_only:true`."
    )
    return system, user


async def inspect_with_ai(
    cfg: AIConfig,
    elements: list[dict[str, Any]],
    overview: dict[str, Any],
    page_url: str,
) -> dict[str, Any]:
    knowledge = load_knowledge()
    system, user = _build_prompt(elements, overview, knowledge, page_url)
    try:
        raw = chat(cfg, system, user, want_json=True)
    except Exception as e:
        return {
            "page_purpose": "(AI çağrısı başarısız)",
            "items": [],
            "_error": f"{type(e).__name__}: {e}",
        }
    try:
        return parse_json(raw)
    except Exception as e:
        return {
            "page_purpose": "(AI yanıtı parse edilemedi)",
            "items": [],
            "_error": f"{type(e).__name__}: {e}",
            "_raw": raw[:1000],
        }


def _signature(el: dict[str, Any]) -> tuple:
    return (el.get("kind"), el.get("label", ""), el.get("name", ""),
            el.get("placeholder", ""), el.get("type", ""))


async def retag_and_remap(page, annotated: list[dict[str, Any]]) -> int:
    """DOM yeniden render edildiyse mevcut data-uitester-id'leri sil, yeniden
    tag'le ve eski annotated kayıtları için label/name/placeholder eşleşmesiyle
    yeni id'yi bul. el['_alive'] = False ise eleman DOM'dan kaybolmuş demektir.

    Geri dönüş: hâlâ canlı olan eleman sayısı."""
    fresh = await tag_elements(page, clear_existing=True)
    by_sig = {}
    for n in fresh:
        by_sig.setdefault(_signature(n), n)
    # gevşek eşleşme için label-only fallback
    by_label = {}
    for n in fresh:
        if n.get("label"):
            by_label.setdefault((n["kind"], n["label"]), n)

    alive = 0
    for el in annotated:
        match = by_sig.get(_signature(el))
        if not match:
            match = by_label.get((el.get("kind"), el.get("label", "")))
        if match:
            el["id"] = match["id"]
            el["in_nav"] = match.get("in_nav", el.get("in_nav", False))
            el["_alive"] = True
            alive += 1
        else:
            el["_alive"] = False
    return alive


def annotate(elements: list[dict[str, Any]], inspection: dict[str, Any]) -> list[dict[str, Any]]:
    """Inspector çıktısını element listesine birleştir. AI sadece field_meaning
    ve buton expected_action verir; test değerleri Python tarafında
    deterministik üretilir (value_generator)."""
    from src.value_generator import values_for

    by_id = {it.get("id"): it for it in inspection.get("items", [])}
    merged = []
    for el in elements:
        ann = dict(by_id.get(el["id"], {}))
        # nav öğeleri test edilmesin
        if el.get("in_nav"):
            ann["should_test"] = False
            ann["is_navigation_only"] = True
        # AI bahsetmediği elemana default
        if "should_test" not in ann:
            ann["should_test"] = not el.get("in_nav", False)

        if el["kind"] == "input" and ann.get("should_test"):
            fm = ann.get("field_meaning") or ""
            dom_attrs = {
                "type": el.get("type", ""),
                "min": el.get("min", ""),
                "max": el.get("max", ""),
                "minlength": el.get("minlength", ""),
                "maxlength": el.get("maxlength", ""),
                "pattern": el.get("pattern", ""),
            }
            valid, invalid = values_for(fm, dom_attrs)
            ann["valid_values"] = valid
            ann["invalid_values"] = invalid
            if not fm:
                ann["field_meaning"] = "unknown"
        merged.append({**el, **ann})
    return merged
