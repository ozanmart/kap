# KAP geliştirme raporu

Güncelleme: 2026-09-02

Bu dosya doğrulanmış kod durumu ve çalıştırma prosedürünü özetler. Önceki
raporlardaki sabit hız/RAM/başarı rakamları kaldırıldı; bunlar yeniden
ölçülmeden ürün iddiası olarak kullanılamaz.

## Tamamlanan düzeltmeler

- KAP şirket listesi için RSC-first parser ve gerçek HTML fixture regresyonu.
- Şirket genel bilgi alanlarında section-scoped HTML lookup; iletişim tablosuna
  sıçrayan global `find_next` davranışı kaldırıldı.
- Detail sayfasında RSC metadata, disclosure id/tarih/ticker/şirket ve
  attachment metadata ayrıştırması.
- Ticker filtresi exact token eşleşmesine çevrildi; substring false-positive
  davranışı kaldırıldı.
- Takvimde ticker geri çözümleme, placeholder eleme, canonical dedup ve sıralama.
- Finansal HTML modelinde tekrar eden dönemlerin korunması, `Decimal`,
  currency/scale/reported/normalized alanları ve metric filtreleri.
- `get_financials(ticker, year, period)` doğru gün aralığı ve dönem eşleşmesiyle
  doğru bildirimi buluyor.
- Sync/async istemcilerde ortak versioned cache key; latest/today/detail/calendar
  için TTL ve disk cache.
- HTTP connect/read/write/pool timeout’ları, toplam deadline, 408/429/5xx retry,
  `Retry-After` ve concurrency semaphore.
- Agent çıktılarında `fetched_at`, `source_url`, `stale`, `warnings`, pagination,
  compact/raw; detail için `max_chars`; event çıktısında birden fazla event ve
  evidence span.
- MCP stdio handler’ı structured content döndürüyor ve sync tool işi event loop
  dışında çalışıyor.
- XLS/pandas yolu optional; varsayılan olarak kapalı, HTML motoru runtime’da
  pandas import etmiyor.
- CI Python 3.10–3.14 aralığında wheel kuruyor ve installed-artifact test ediyor.
- Registry canlı akışında operation-wide deadline artık parse aşamasını da
  kapsıyor; `fetch_s`, `ttfb_s`, `download_s`, `parse_s`, `total_s`, stage ve
  attempt bilgileri `last_request_metrics` üzerinden raporlanıyor.
- Stale-while-revalidate cache, son başarılı veriyi anında döndürüp tek
  background refresh çalıştırıyor; `fast`, `balanced`, `resilient` profilleri
  retry/deadline sözleşmesini açıkça tanımlıyor.
- `kap`, `kap.scrapers`, `kap.parsing` ve `kap.models` namespace’leri lazy;
  basit ticker/client yolunda SQLite, MCP ve ilgisiz finans/event modülleri
  yüklenmiyor.
- Canlı registry kabulü ticker regex’i, benzersizlik, minimum satır sayısı ve
  32 karakterlik MKK member OID kontrolünden geçiyor.
- Gerçek KAP capture’larından registry, feed, detail/attachment, financial ve
  company-general fixture’ları eklendi; fixture kaynakları ve capture tarihi
  `tests/fixtures/README.md` içinde kayıtlı.

## Son P0/P1 kapanışları

- SWR yenilemesi artık non-daemon executor kullanmıyor; kısa ömürlü süreç
  kapanışını bekletmeyen daemon thread ile çalışıyor. fast profili background
  refresh’i kapatıyor.
- force_refresh fresh ve stale kayıtları bypass ediyor; async client da sync
  client ile aynı stale-if-error/SWR sözleşmesini ve lazy constructor yolunu
  kullanıyor.
- Her HTTP operasyonu operation_id ve kendi timing/stage bilgisini taşıyor;
  granular timeout değerleri kalan deadline bütçesiyle ayrı ayrı sınırlandırılıyor.
  Parse deadline’ı daemon parser worker ile caller-visible hard deadline oldu.
- Benchmark auto modu proje venv’ini resolve etmeden seçiyor, güncel wheel’i
  otomatik build edip geçici izole ortama kuruyor, dört repo dependency
  preflight yapıyor ve current kap tamamen skipped ise non-zero dönüyor.
- Registry refresh script’i validated diff, atomik JSON/metadata ve haftalık CI
  drift raporu sağlıyor; bundled snapshot için minimum kayıt/OID CI testi eklendi.

## Doğrulama

```bash
source .venv/bin/activate
python -m pytest -q
python -m build --wheel
```

`pytest` mevcut source/wheel ayrımını ve lazy import sözleşmesini doğrular.
macOS Desktop/iCloud altında `compileall` dosya hidrasyonu nedeniyle yavaş
olabilir; CI wheel üzerinde derleme/test yapar.

Dış KAP ağına bağlı testler ayrıca ve düşük yoğunlukta çalıştırılmalıdır:

```bash
python -m benchmarks.run --profile smoke
python -m benchmarks.run --profile smoke --live --live-iterations 1
```

Benchmark çıktıları `benchmark-results/latest.json` ve `latest.md` dosyalarına
yazılır. `error`, `timeout` ve `Correct: no` sonuçları başarı kabul edilmez.
Public KAP endpoint’ine 1.000 eşzamanlı istek gönderilmez; gerçek async
benchmark farklı disclosure URL’leri, concurrency 1/4/8, connection reuse,
cancellation ve ortak deadline ile yapılmalıdır.

## Bilinen sınır

`bist-investment-agent` içindeki MKK provider, attachment downloader ve
incremental checkpoint backend’i yalnızca `src/kap/backends/optional.py` altında
opsiyonel protokol olarak taşındı. Kaynak projenin `Proprietary` bildirimi
nedeniyle bu repository MIT olarak dağıtılamaz; provenance/redistribution izni
alınana kadar lisans durumu `Proprietary / pending provenance clearance` olarak
kalır. Ayrıntı: [PROVENANCE_AUDIT.md](/Users/omerozanmart/Desktop/kap/PROVENANCE_AUDIT.md).
