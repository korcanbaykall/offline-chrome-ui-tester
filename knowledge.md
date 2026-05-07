# Şirket Bilgi Tabanı (AI'ya verilir)

Bu dosya her AI çağrısında prompt'a eklenir. Buraya şirketinize özgü
kuralları, alan formatlarını ve mantıksal kısıtlamaları yazın. Sade, kısa,
liste hâlinde tutun.

## Test felsefesi: "geçersiz değer" ne demek

Sayfa zaten input'a yazılmasını engellediği değerler **geçersizlik testi
değildir**. Örneğin `type="tel"` ya da `pattern="[0-9]{10}"` olan bir alana
"abc" veya "-1" girmek anlamsız — input bunu zaten yazmaz, "validation çalıştı"
diye onay vermez. Doğru geçersiz değer **input'a yazılır ama sayfa mantığına
aykırıdır** (örn telefon formatı doğru ama operatör kodu yok, yaş 200, e-posta
domain'i imkânsız).

## Genel mantıksal kurallar

- **Yaş**: 0-150 arası tam sayı. Negatif, ondalık, harf veya >150 reddedilmeli.
- **TC Kimlik No**: 11 hane, sadece rakam, ilk hane 0 olamaz.
- **Telefon (TR)**: 10 hane (5XX XXX XX XX), başında 0 olabilir veya olmayabilir.
  Harf ve özel karakter reddedilmeli.
- **E-posta**: standart RFC formatı, `@` ve `.` içermeli.
- **Şifre**: en az 8 karakter, en az bir harf bir rakam (varsayılan).
- **Tarih**: gerçekçi aralık (1900-bugün+10), DD.MM.YYYY veya YYYY-MM-DD.
- **Para tutarı**: pozitif sayı, en fazla 2 ondalık.
- **IBAN (TR)**: TR + 24 hane.

## Beklenen buton davranışları

- "Giriş Yap / Login": geçerli kimlikle dashboard'a yönlendirmeli, geçersizle
  hata mesajı göstermeli (sayfa aynı kalmalı).
- "Kayıt Ol / Submit": form geçerliyse onay/yönlendirme, geçersizse alan
  bazında hata mesajı.
- "İptal / Vazgeç": modal kapanmalı veya önceki sayfaya dönmeli, veri
  kaydedilmemeli.
- "Sil": onay sorması beklenir, doğrudan silmek genelde hatadır.

## Notlar

- Buraya sayfa-spesifik kurallar da eklenebilir (örn. "kredi başvuru formunda
  gelir alanı 0'dan büyük olmalı").
- AI bu kuralları gördüğünde input'lara uygun geçerli/geçersiz değerler üretir
  ve butonların davranışını bu kurallara göre değerlendirir.
