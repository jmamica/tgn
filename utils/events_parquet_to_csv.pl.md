# Konwerter Events Parquet

`events_parquet_to_csv.py` konwertuje pliki parquet z `data_raw/events/` do surowego formatu CSV
oczekiwanego przez istniejący pipeline TGN, analogicznie do `reddit.csv` i `wikipedia.csv`.

Konwerter używa też artefaktów pomocniczych z `data_raw/preprocess/`, jeśli są dostępne.

## Wejście

Domyślnie konwerter czyta:

```bash
data_raw/events/events_v1.parquet
```

Wykryty schemat danych zdarzeń:

```text
src, dst, timestamp, event_type, dt_bucket, has_media, url_count_bucket,
char_count_bucket, url_hash, domain
```

Mapowanie do formatu TGN:

```text
src -> user
dst -> item
timestamp -> timestamp
label -> state_label, domyślnie 0.0
```

Nazwy `user` i `item` pochodzą z oryginalnego formatu CSV JODIE/TGN. W tym projekcie nie muszą
oznaczać dosłownie użytkownika i produktu/elementu. Dla danych Telegrama:

```text
user -> endpoint źródłowy, zwykle kanał źródłowy
item -> endpoint docelowy, zwykle kanał docelowy
```

Kod treningowy oczekuje takiego układu kolumn, dlatego konwerter zachowuje nazwy `user` i `item`
jako format kompatybilności, nawet jeśli realnymi obiektami są kanały Telegrama.

## Kodowanie Cech

Ta implementacja TGN czyta cechy interakcji z `data/ml_<name>.npy`, więc konwerter sprowadza
wszystkie używane informacje do poziomu cech krawędzi.

Kolumny zdarzeń są obsługiwane tak:

```text
dt_bucket -> numeryczna cecha krawędzi
has_media -> numeryczna cecha krawędzi
url_count_bucket -> numeryczna cecha krawędzi
char_count_bucket -> numeryczna cecha krawędzi
event_type -> kategoryczna cecha one-hot
url_hash -> domyślnie pomijany
domain -> domyślnie pomijany
```

Typ zdarzenia `event_type` jest kodowany one-hot. Dla obecnych danych powstają kolumny:

```text
event_type_FORWARD
event_type_SAME_URL
```

Przykład:

```text
FORWARD  -> event_type_FORWARD=1.0, event_type_SAME_URL=0.0
SAME_URL -> event_type_FORWARD=0.0, event_type_SAME_URL=1.0
```

Kolumny tekstowe o dużej liczbie wartości, takie jak `url_hash` i `domain`, są celowo pomijane.
Bezpośrednie one-hot encoding dla tych pól byłoby zbyt kosztowne i ryzykowne. Jeśli te informacje
mają wejść do modelu, lepsze są kontrolowane strategie: top-K domen, hashing trick albo osobny
embedding.

## Artefakty Preprocessingu

Jeśli istnieje `data_raw/preprocess/`, konwerter używa:

```text
data_raw/preprocess/channel_filter_v1.csv
data_raw/preprocess/channel_stats.parquet
data_raw/preprocess/style_features.parquet
```

`channel_filter_v1.csv` jest stosowany domyślnie. Eksportowane są tylko zdarzenia, w których zarówno
`src`, jak i `dst` mają `kept=True`.

Wyłączenie filtrowania:

```bash
python3 utils/events_parquet_to_csv.py --no-channel-filter
```

`channel_stats.parquet` i `style_features.parquet` są domyślnie dołączane jako cechy obu końców
krawędzi. Każda kolumna numeryczna trafia do danych dwa razy:

```text
src_<nazwa_kolumny>
dst_<nazwa_kolumny>
```

Przykładowe kolumny stylu:

```text
src_hour_entropy
src_night_ratio_utc_00_05
src_delta_mean_s
src_delta_std_s
src_delta_cv
src_has_media_ratio
src_url_msg_ratio
dst_hour_entropy
dst_night_ratio_utc_00_05
...
```

Przykładowe statystyki kanałów:

```text
src_total_messages
src_forward_messages
src_forward_ratio
src_url_messages
src_url_ratio
src_span_days
src_avg_msgs_per_day
dst_total_messages
dst_forward_ratio
...
```

Wyłączenie cech kanałów:

```bash
python3 utils/events_parquet_to_csv.py --no-channel-features
```

Inny katalog preprocessingu:

```bash
python3 utils/events_parquet_to_csv.py --preprocess-dir path/to/preprocess
```

## Format Wyjścia

Surowy CSV ma format zgodny z JODIE:

```text
user,item,timestamp,state_label,feature_0,feature_1,...
```

Domyślnie plik pośredni jest zapisywany w `data_raw/`, np.:

```text
data_raw/events.csv
```

Następnie `utils/preprocess_data.py` tworzy pliki wymagane przez trening:

```text
data/ml_<name>.csv
data/ml_<name>.npy
data/ml_<name>_node.npy
```

## Podstawowy Przepływ

```bash
python3 utils/events_parquet_to_csv.py --sort
python3 utils/preprocess_data.py --data events --input-dir data_raw --output-dir data --bipartite
```

## Flagi Konwertera

`--shared-node-space` zmienia sposób kodowania identyfikatorów końców krawędzi przed zapisaniem
surowego CSV.

Bez tej flagi `src` i `dst` są kodowane niezależnie:

```text
src channel A -> user id 10
dst channel A -> item id 25
```

Z `--shared-node-space` obie kolumny używają jednej wspólnej przestrzeni identyfikatorów:

```text
src channel A -> user id 10
dst channel A -> item id 10
```

Używaj `--shared-node-space`, gdy `src` i `dst` są tą samą klasą obiektów, np. kanałami Telegrama.
W tym wariancie `utils/preprocess_data.py` należy uruchomić bez `--bipartite`.

`--sort` sortuje interakcje po timestampie przed zapisaniem surowego CSV. Jest to ważne dla modeli
temporalnych: split train/validation/test w `utils/data_processing.py` bazuje na kwantylach czasu,
a aktualizacje pamięci TGN są najłatwiejsze do interpretacji, gdy zdarzenia są zapisane
chronologicznie. Sortowanie jest stabilne, więc zdarzenia z tym samym timestampem zachowują swoją
kolejność wejściową.

## Okna Czasowe

Pliki `splits_*.json` zawierają granice timestampów. Przykład dla okna 5M:

```bash
python3 utils/events_parquet_to_csv.py \
  --split-file data_raw/events/splits_5M_v1.json \
  --output data_raw/events_5M.csv \
  --sort

python3 utils/preprocess_data.py \
  --data events_5M \
  --input-dir data_raw \
  --output-dir data \
  --bipartite
```

Aby wyeksportować pełny zbiór, pomiń `--split-file`:

```bash
python3 utils/events_parquet_to_csv.py \
  --output data_raw/events_full.csv \
  --sort

python3 utils/preprocess_data.py \
  --data events_full \
  --input-dir data_raw \
  --output-dir data \
  --bipartite
```

## Tryby Kodowania Węzłów

Domyślny tryb koduje `src` i `dst` osobno. Jest zgodny z dotychczasowym preprocessingiem
bipartite:

```bash
python3 utils/events_parquet_to_csv.py --output data_raw/events.csv --sort
python3 utils/preprocess_data.py --data events --input-dir data_raw --output-dir data --bipartite
```

`--bipartite` jest opcją skryptu `utils/preprocess_data.py`, a nie samego konwertera parquet.
Oznacza, że pierwsza kolumna CSV (`user`) i druga kolumna CSV (`item`) są traktowane jako dwa
rozłączne zbiory węzłów. Wewnątrz preprocessingu identyfikatory destination są przesuwane o
`max(user) + 1`, a potem wszystkie identyfikatory węzłów są przesuwane o jeden, ponieważ indeks `0`
jest w TGN zarezerwowany jako padding/pusty identyfikator.

To jest poprawne dla oryginalnych zbiorów w stylu JODIE:

```text
wikipedia: user -> page
reddit: user -> subreddit/post/thread-like item
```

W takich danych `user=42` i `item=42` nie oznaczają tego samego obiektu. To dwie różne przestrzenie
identyfikatorów, więc trzeba je rozdzielić.

Jeśli `src` i `dst` oznaczają tę samą klasę obiektów, np. kanały Telegrama, sensowniejsza
semantycznie jest wspólna przestrzeń węzłów:

```bash
python3 utils/events_parquet_to_csv.py \
  --shared-node-space \
  --output data_raw/events.csv \
  --sort

python3 utils/preprocess_data.py --data events --input-dir data_raw --output-dir data
```

Dla Telegrama, jeśli zarówno `src`, jak i `dst` są identyfikatorami kanałów, wariant
`--shared-node-space` oraz preprocessing bez `--bipartite` zwykle lepiej oddaje semantykę grafu.
Kanał `1001` pozostaje wtedy tym samym węzłem niezależnie od tego, czy występuje jako źródło, czy
jako cel. Użycie `--bipartite` sztucznie rozdzieliłoby go na dwa węzły: kanał-źródło `1001` i
kanał-cel `1001`.

Rekomendowany wariant bazowy dla Telegrama ze splitem 5M:

```bash
python3 utils/events_parquet_to_csv.py \
  --shared-node-space \
  --split-file data_raw/events/splits_5M_v1.json \
  --output data_raw/events_5M.csv \
  --sort

python3 utils/preprocess_data.py --data events_5M --input-dir data_raw --output-dir data
```

Rekomendowany wariant bazowy dla Telegrama na pełnym zbiorze:

```bash
python3 utils/events_parquet_to_csv.py \
  --shared-node-space \
  --output data_raw/events_full.csv \
  --sort

python3 utils/preprocess_data.py --data events_full --input-dir data_raw --output-dir data
```

## Smoke Test

```bash
python3 utils/events_parquet_to_csv.py \
  --max-rows 100 \
  --print-schema \
  --output data_raw/events_sample.csv \
  --sort

python3 utils/preprocess_data.py \
  --data events_sample \
  --input-dir data_raw \
  --output-dir data \
  --bipartite
```

Jeśli filtrowanie kanałów jest włączone, próbka może mieć mniej rekordów niż `--max-rows`, bo limit
jest nakładany przy odczycie parquetu, a potem usuwane są kanały spoza `channel_filter_v1.csv`.

## Krytyka Dopasowania Danych Telegrama do TGN Rossiego

To mapowanie jest użyteczne technicznie, ale nie jest idealnym dopasowaniem semantycznym do
oryginalnej implementacji TGN Rossiego.

Po pierwsze, oryginalne zbiory `wikipedia` i `reddit` są naturalnie bipartite: użytkownik wchodzi w
interakcję z elementem. Dane Telegrama typu `FORWARD` i `SAME_URL` są bliżej grafu kanał-kanał. Jeśli
`src` i `dst` są kanałami, tryb `--shared-node-space` jest bardziej poprawny znaczeniowo niż
`--bipartite`. Tryb bipartite zostaje głównie dla kompatybilności z pipeline'em.

Po drugie, cechy stylu kanału są statyczne. Jeśli zostały policzone na całym zakresie czasu, mogą
wprowadzać leakage: event treningowy dostaje cechy obliczone z przyszłych wiadomości. Przy ścisłej
ewaluacji temporalnej należy liczyć `channel_stats` i `style_features` wyłącznie z danych dostępnych
przed granicą treningu albo osobno dla każdego splitu.

Po trzecie, `state_label=0.0` jest tylko wypełniaczem, gdy brak kolumny etykiety. To wystarcza dla
self-supervised link prediction, gdzie model uczy się odróżniać prawdziwe interakcje od negatywnych
próbek. Nie jest to jednak sensowny target dla `train_supervised.py`. Zadanie supervised wymaga
oddzielnej definicji etykiety.

Po czwarte, `FORWARD` i `SAME_URL` są różnymi relacjami. One-hot encoding informuje model o typie
zdarzenia, ale TGN nadal traktuje dane jako jeden strumień temporalnych interakcji. Jeżeli typ relacji
ma być centralny dla zadania, lepszy może być model relacyjny albo osobne mechanizmy próbkowania dla
różnych typów relacji.

Po piąte, pominięcie `domain` i `url_hash` jest bezpieczne obliczeniowo, ale traci sygnał. Domeny
mogą dobrze opisywać podobieństwo kanałów, a hash URL może wykrywać koordynację. Trzeba je jednak
dodawać ostrożnie: top-K domen, hashing trick albo embedding, nie pełny one-hot.

Po szóste, skale cech są bardzo różne. Cechy binarne, liczniki, timestampy i delty czasu trafiają do
jednej macierzy cech krawędzi. Bez normalizacji model może nadmiernie reagować na duże wartości.
Warto rozważyć standaryzację/log-transformację liczników i delt przed treningiem.

Po siódme, obecny pipeline nie tworzy prawdziwych cech węzłów. `ml_<name>_node.npy` pozostaje
macierzą zerową. Cechy kanałów są więc replikowane jako cechy krawędzi. To działa pragmatycznie, ale
nie wykorzystuje w pełni konstrukcji TGN, w której cechy węzłów mogłyby reprezentować kanały
bez powtarzania tych samych wartości przy każdej interakcji.

Najrozsądniejszy wariant bazowy dla Telegrama to:

```bash
python3 utils/events_parquet_to_csv.py \
  --shared-node-space \
  --sort

python3 utils/preprocess_data.py --data events --input-dir data_raw --output-dir data
```

Jeżeli celem jest porównywalność z oryginalnym pipeline'em `wikipedia/reddit`, można zostać przy
trybie bipartite, ale w raporcie warto wyraźnie zaznaczyć, że jest to adaptacja techniczna, a nie
naturalna semantyka grafu Telegrama.

## Wymagania

```text
pandas
numpy
pyarrow lub inny silnik parquet obsługiwany przez pandas
```
