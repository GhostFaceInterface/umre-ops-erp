# Umre Ops Codex çalışma sözleşmesi

## Amaç

Bu depo ERPNext/Frappe üzerinde çalışan finansal etkili bir Umre operasyon uygulamasıdır. Öncelik; muhasebe doğruluğunu, veri bütünlüğünü ve geri alınabilir değişiklikleri koruyarak sistemi adım adım iyileştirmektir.

## İlk okuma sınırı

- Her işe `git status --short` ve dar kapsamlı `rg`/dosya okumalarıyla başla.
- `docs/` ve `umre_ops/umre_ops/docs/` klasörlerini topluca okuma. Yalnızca kullanıcı açıkça izin verdiğinde veya görev belirli bir belgeyi zorunlu kıldığında ilgili dosyayı hedefli oku.
- Gizli bilgi olabilecek `.env`, site yapılandırmaları, yedekler ve veritabanı dökümlerini okuma ya da çıktıya taşıma.
- Kullanıcının mevcut kirli worktree değişikliklerini koru; ilişkisiz dosyaları düzenleme, geri alma veya formatlama.

## Repo haritası

- Frappe uygulama paketi: `umre_ops/`
- İş mantığı: `umre_ops/umre_ops/services/`
- DocType şema/controller/UI: `umre_ops/umre_ops/doctype/`
- Rapor ve Desk yüzeyleri: `umre_ops/umre_ops/report/`, `umre_ops/umre_ops/page/`, `umre_ops/public/`
- Kurulum ve göçler: `umre_ops/patches.txt`, `umre_ops/patches/`, `umre_ops/hooks.py`
- CI: `.github/workflows/`
- Docker/operasyon betikleri: `docker-setup/`, `backups/`

Çift görünen paket veya patch yollarından birini tahminle silme. Aktif import/hook/patch zincirini kanıtla.

## Değişmezler

- Para için ikili kayan nokta varsayımı yapma; mevcut Frappe/Decimal dönüşüm ve yuvarlama politikasını izle.
- Muhasebe kaydı, ödeme, masraf, kur dönüşümü ve maliyet hesabında idempotency, şirket, para birimi, hesap, cost center, tarih ve iptal davranışını birlikte doğrula.
- DocType alan değişikliklerinde JSON şeması, Python controller/service, istemci JS, izinler, fixture/patch ve test etkisini birlikte incele.
- Şema veya veri göçleri ileriye uyumlu, tekrar çalıştırılabilir ve mevcut veriyi koruyacak biçimde olmalı. Üretim verisi üzerinde komut çalıştırma.
- Whitelisted metotlarda yetki, girdi doğrulama ve sunucu tarafı iş kuralı zorunludur; yalnızca istemci doğrulamasına güvenme.
- Üretim deploy'u, migrate, patch, yedekleme/geri yükleme veya gerçek siteye yazan `bench execute` komutları açık kullanıcı talebi olmadan çalıştırılmaz.

## Ajan orkestrasyonu

Karmaşık işler için `$orchestrate-umre-ops` skill'ini kullan. Basit ve tek dosyalı bir işte alt ajan başlatma.

- Okuma-ağırlıklı, birbirinden bağımsız incelemeler paralel olabilir.
- Aynı anda en fazla üç alt ajan kullan.
- Yazma yetkisi tek ajanda kalır. Paralel ajanlara aynı dosyalarda değişiklik yaptırma.
- Alt ajana yalnızca amaç, kapsam yolları, kısıtlar ve beklenen kısa çıktı ver; tüm konuşmayı yeniden anlatma.
- Önce kanıt topla, sonra tek uygulayıcı değişiklik yapsın, en son bağımsız inceleme/test gerçekleştirilsin.
- Alt ajan çıktısı ham log değil; dosya/simge referanslı bulgu, risk, doğrulama ve belirsizlik özeti olmalı.

Özel roller `.codex/agents/` altındadır:

- `repo_explorer`: hızlı, salt-okunur yol ve bağımlılık haritalama
- `frappe_architect`: Frappe/ERPNext yaşam döngüsü, DocType, hook ve migration analizi
- `finance_guardian`: muhasebe, para birimi, posting ve idempotency denetimi
- `test_analyst`: mevcut test yüzeyi ve en küçük doğrulama planı
- `implementation_worker`: kanıtlandıktan sonra tek-yazar uygulama
- `change_reviewer`: değişiklik sonrası bağımsız regresyon ve risk incelemesi

## Doğrulama

Önce en dar doğrulamayı çalıştır, sonra risk gerektiriyorsa genişlet:

```bash
pre-commit run --files <changed-files>
```

Frappe testleri bench kökünden, kullanıcı tarafından belirtilen veya güvenli biçimde keşfedilen test sitesiyle çalıştırılır:

```bash
bench --site <test-site> run-tests --app umre_ops --module <python.module>
bench --site <test-site> run-tests --app umre_ops
```

Test sitesi yoksa veya komut gerçek veriye dokunabilecekse bunu çalıştırma; hangi doğrulamanın eksik kaldığını açıkça bildir. Değişiklik tesliminde çalıştırılan komutları, sonuçları ve çalıştırılamayan kontrolleri özetle.

## Çıktı standardı

- İnceleme: önem sırasına göre somut bulgular, dosya/simge referansı, etki ve önerilen doğrulama.
- Uygulama: sonuç, değişen dosyalar, testler ve kalan riskler.
- Belirsizliği gerçekmiş gibi yazma; varsayımı ve onu doğrulayacak kanıtı belirt.
