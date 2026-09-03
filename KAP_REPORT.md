# KAP teknik durum raporu

Güncelleme: 2026-09-03

## 2026-09-03 final kalite kapısı

- Source tree testleri `109 passed` sonucunu verdi. Üretim wheel'i mevcut build
  araçlarıyla tekrar oluşturulup import/CLI smoke testinden geçti; wheel içeriği
  yeni lazy component, validation, exception ve `py.typed` dosyalarını taşıyor;
  dağıtım metadata’sında `License-Expression: MIT` bulunuyor.
- Yeni public quality testleri shared exception alias'ını, sync/async tarihsel
  subject varsayılanını, parametre validasyonunu, market TTL ayrımını ve
  idempotent SQLite kapanışını doğruluyor.
- Public-KAP-only source gate üç bağımsız cold balanced koşuda 3/3 geçti;
  registry istekleri sırasıyla 3.270 s, 2.610 s ve 2.534 s sürdü ve her biri
  ilk denemede tamamlandı. Final wheel'in 17 maddelik tam canlı kapısı da geçti.
- Tarayıcı şirket sayfasındaki 755 şirket satırı, çoklu kod hücreleri ayrılınca
  805 benzersiz ticker üretti; online SDK ve bundled snapshot aynı 805 ticker'ı
  verdi. Snapshot raw SHA-256 değeri metadata ile eşleşti.
- İstanbul günü bildirim kümesi tarayıcı ve SDK arasında karşılaştırılırken yeni
  `1657832` bildirimi geldi. İkinci tarayıcı yenilemesinde iki taraf 85 ID ile
  birebir eşleşti; eksik ve duplicate kalmadı.
- Stdio MCP initialize/list/call/shutdown akışı 10 tool ile geçti ve stdout'a
  JSON-RPC dışı çıktı sızmadı. Final wheel CLI gate'indeki sekiz senaryo da
  geçti.
- Standard dört-repo offline benchmark 152 işi `1,5,10,25,50` yükleriyle
  tamamladı. Ayrı düşük yoğunluklu canlı benchmark seri çalıştı. Yanlış veya
  eksik sonuçlar hız galibiyeti sayılmadı.

Kanıt artefaktları:

- `benchmark-results/latest.json` ve `benchmark-results/latest.md`
- `benchmark-results/live-four-repo/latest.json` ve `latest.md`
- `benchmark-results/live-validation-source.json`
- `benchmark-results/live-validation-source-run2.json`
- `benchmark-results/live-validation-source-run3.json`
- `benchmark-results/live-validation-wheel.json`
- `benchmark-results/cli-validation-wheel.json`

## Mimari

Paket `KapClient` ve `AsyncKapClient` olmak üzere iki API sunar. Ağ katmanı
paylaşılan `httpx` client’ları, toplam request deadline, retry/backoff ve async
concurrency semaphore kullanır. Parsers browser bağımlılığı olmadan KAP’ın RSC
payload’larını ve server-rendered HTML tablolarını işler.

Ana akışlar:

- şirket registry: bundled snapshot + tek seferlik O(1) ticker/name/member-OID
  indexleri; canlı registry RSC-first ve HTML fallback;
- şirket profili: section-scoped scalar/table parsing, shareholder/free-float/
  subsidiary alanları;
- disclosures: Europe/Istanbul gününün tamamını döndüren byCriteria sorgusu,
  latest/ticker geçmişi, historical criteria, detail metadata ve attachment
  metadata;
- financials: HTML taxonomy motoru, tekrar eden dönemler, Decimal değerler,
  currency/scale; XLS backend açıkça opt-in;
- events: bir disclosure’dan birden çok event ve evidence span;
- agent: Pydantic şemaları, OpenAI/Anthropic tanımları ve MCP structured output;
- persistence: TTL’li memory + disk cache ve opsiyonel SQLite.

## Cache ve veri güvenilirliği

Cache anahtarları parser schema version, dil ve sorgu parametrelerini içerir.
Latest/today kısa TTL, detail uzun TTL kullanır. Cache metadata’sı
`fetched_at`, `stale` ve `warnings` alanlarına aktarılır. Ticker filtreleri
substring yerine exact token eşleştirmesi yapar. Takvim placeholder satırlarını
çıkarır ve canonical key ile tekrarları siler.

Live registry için socket timeout’a ek operation-wide deadline vardır; HTTP
fetch, TTFB, body download ve parse süreleri ayrı ölçülür. Fresh TTL dışındaki
başarılı değer stale olarak tutulur. `fast` tek deneme + stale fallback,
`balanced` varsayılan, `resilient` daha geniş deadline ve retry bütçesi kullanır.
Deadline tek HTTP çağrısı için değil, cache beklemesi, semaphore kuyruğu, retry,
indirme ve parse dahil bütün client operasyonu için geçerlidir.
Package root ve namespace paketleri lazy import kullanır; default client
oluşturmak SQLite/MCP/finansal parser graph’ını yüklemez. Live registry ticker
formatı, benzersizlik, minimum satır sayısı ve public KAP member OID
doğrulamasından geçmeden
kabul edilmez. Gerçek capture fixture’ları `tests/fixtures/` altında bulunur.

Sync ve async istemciler scraper bileşenlerini ortak lazy component factory
üzerinden wire eder. Public exception sınıfları HTTP katmanından ayrılmıştır;
eski `kap.scrapers.base` importları geriye dönük uyumluluk için korunur.
Cache memory katmanı eşzamanlı refresh işlemlerinde thread-safe erişim kullanır;
public client argümanları ağ çağrısından önce doğrulanır.

## Son P0/P1 kapanışları

SWR yenilemesi non-daemon executor yerine daemon worker kullanır; fast profilinde
background refresh kapalıdır. force_refresh fresh ve stale cache’i bypass eder;
async client da aynı cache/fallback sözleşmesini uygular. Her operasyon kendine
ait operation ID ve metrik setini taşır. Registry snapshot yenilemesi
scripts/refresh_registry.py ile atomik JSON/metadata yazımı, diff raporu ve CI
drift kontrolü üzerinden yürür.

## Finansal veri sözleşmesi

`FinancialStatement.period_labels` tüm dönemleri korur. Her satırda
`reported_value`, `value_numeric`, `normalized_value`, `currency` ve `scale`
alanları bulunabilir. Agent compact modu geçmiş scalar şeklini korur; `compact:
false` her metriği `{period: value}` biçiminde döndürür. `get_financials` ticker
ve yayın yılı seçicilerini KAP'ın güncel Finansal Rapor subject OID'siyle
sorgular; sorumluluk/faaliyet raporlarını dışarıda bırakır ve optional period
ile doğru finansal bildirimi seçer.

## Benchmark politikası

Eski sabit performans tabloları geçerli ölçüm olarak kabul edilmez. Güncel ölçüm
şu komutla üretilir:

```bash
python -m benchmarks.run --profile standard
```

Her senaryo ayrı subprocess’te çalışır, fixture replay correctness kontrolü
yapar ve unsupported capability’leri `skipped` olarak raporlar. Live senaryolar
opt-in’dir; public KAP’a yapay 1.000-concurrency yük testi yapılmaz.

Public-KAP semantic release gate `python -m scripts.validate_live_kap` komutudur.
Bu kapı 10 agent tool'unun tamamını, sync/async parity'yi ve isteğe bağlı global
takvimi seri ve düşük yoğunlukta doğrular; MKK/MKK REST çağrısı yapmaz.

## Paketleme ve ortam

Geliştirme ortamı repository-local Python 3.13 `.venv`’dir. Runtime install
wheel tabanlıdır; editable install yalnızca aktif source geliştirme sırasında
kullanılmalıdır. CI Python 3.10–3.14 üzerinde temiz wheel kurulumunu test eder.

## Lisans/provenance

Repository metadata’sı ve `LICENSE` artık MIT olarak ayarlandı. Önceki audit,
referans projelerin Proprietary bildirimini ve bu repository’de eksik olan
file-by-file provenance kaydını belgeliyor. MIT dağıtımı yapmadan önce
maintainer, dahil edilen kodun yeniden dağıtım hakkını ve audit kaydını teyit
etmelidir. Ayrıntı [PROVENANCE_AUDIT.md](PROVENANCE_AUDIT.md).
