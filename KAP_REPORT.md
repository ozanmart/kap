# KAP teknik durum raporu

Güncelleme: 2026-09-02

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
- disclosures: main feed, today/latest, historical criteria, detail metadata ve
  attachment metadata;
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
Package root ve namespace paketleri lazy import kullanır; default client
oluşturmak SQLite/MCP/finansal parser graph’ını yüklemez. Live registry ticker
formatı, benzersizlik, minimum satır sayısı ve MKK OID doğrulamasından geçmeden
kabul edilmez. Gerçek capture fixture’ları `tests/fixtures/` altında bulunur.

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
false` her metriği `{period: value}` biçiminde döndürür. `get_financials` ticker,
year ve optional period ile bildirimi bulur.

## Benchmark politikası

Eski sabit performans tabloları geçerli ölçüm olarak kabul edilmez. Güncel ölçüm
şu komutla üretilir:

```bash
python -m benchmarks.run --profile standard
```

Her senaryo ayrı subprocess’te çalışır, fixture replay correctness kontrolü
yapar ve unsupported capability’leri `skipped` olarak raporlar. Live senaryolar
opt-in’dir; public KAP’a yapay 1.000-concurrency yük testi yapılmaz.

## Paketleme ve ortam

Geliştirme ortamı repository-local Python 3.13 `.venv`’dir. Runtime install
wheel tabanlıdır; editable install yalnızca aktif source geliştirme sırasında
kullanılmalıdır. CI Python 3.10–3.14 üzerinde temiz wheel kurulumunu test eder.

## Lisans/provenance

Repository’nin mevcut metadata’sı `Proprietary` ve provenance clearance
bekliyor. `bist-investment-agent` metadata’sı da Proprietary olduğu için MIT
iddiası yapılmıyor. Hukuki/redistribution izinleri alınmadan public release
yapılmamalıdır. Ayrıntı [PROVENANCE_AUDIT.md](/Users/omerozanmart/Desktop/kap/PROVENANCE_AUDIT.md).
