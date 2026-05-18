# Rekomendacje uruchomienia TGN dla zbioru Telegram

Ten dokument opisuje rekomendowany, krokowy proces przygotowania danych Telegram,
treningu modelu TGN oraz weryfikacji baseline'ow w tym repozytorium.

## 1. Srodowisko

W repozytorium dostepne jest lokalne srodowisko `.venv`. Domyslny `python3` moze
nie widziec zaleznosci projektu, dlatego wszystkie komendy ponizej uruchamiaj przez:

```bash
.venv/bin/python ...
```

## 2. Smoke test danych

Najpierw sprawdz schemat i mala probke danych:

```bash
.venv/bin/python utils/events_parquet_to_csv.py \
  --max-rows 10000 \
  --print-schema \
  --shared-node-space \
  --output data_raw/events_sample.csv \
  --sort

.venv/bin/python utils/preprocess_data.py \
  --data events_sample \
  --input-dir data_raw \
  --output-dir data
```

Dla danych Telegram rekomendowany jest wariant `--shared-node-space`, poniewaz
`src` i `dst` zwykle oznaczaja ten sam typ encji: kanal Telegram. Po takim
eksporcie preprocessing nalezy uruchomic bez flagi `--bipartite`.

## 3. Przygotowanie glownego zbioru 5M

Rekomendowanym pierwszym zbiorem do treningu jest `events_5M`, poniewaz pelny
zbior bedzie znacznie ciezszy obliczeniowo.

```bash
.venv/bin/python utils/events_parquet_to_csv.py \
  --shared-node-space \
  --split-file data_raw/events/splits_5M_v1.json \
  --output data_raw/events_5M.csv \
  --sort

.venv/bin/python utils/preprocess_data.py \
  --data events_5M \
  --input-dir data_raw \
  --output-dir data
```

Aktualny gotowy wariant `events_5M` ma okolo:

- `5,000,001` interakcji,
- `45,738` wezlow,
- `50` cech krawedzi,
- `172` cechy wezlow.

Podzial czasowy jest zgodny ze splitem:

- train do okolo `1724794784`,
- validation do okolo `1726033991`,
- test po `1726033991`.

## 4. Kontrola przecieku danych

Najwieksze ryzyko metodologiczne dotyczy plikow:

- `data_raw/preprocess/channel_stats.parquet`,
- `data_raw/preprocess/style_features.parquet`.

Jesli cechy kanalow zostaly policzone na calym horyzoncie czasu, moga wnosic
informacje z przyszlosci do treningu. Dlatego warto uruchomic co najmniej dwa
warianty eksperymentu.

### Wariant czystszy temporalnie

```bash
.venv/bin/python utils/events_parquet_to_csv.py \
  --shared-node-space \
  --split-file data_raw/events/splits_5M_v1.json \
  --no-channel-features \
  --output data_raw/events_5M_no_channel.csv \
  --sort

.venv/bin/python utils/preprocess_data.py \
  --data events_5M_no_channel \
  --input-dir data_raw \
  --output-dir data
```

### Wariant feature-rich

```bash
.venv/bin/python utils/events_parquet_to_csv.py \
  --shared-node-space \
  --split-file data_raw/events/splits_5M_v1.json \
  --output data_raw/events_5M.csv \
  --sort

.venv/bin/python utils/preprocess_data.py \
  --data events_5M \
  --input-dir data_raw \
  --output-dir data
```

Wariant z cechami kanalow nalezy opisac jako potencjalnie mniej rygorystyczny
temporalnie, chyba ze cechy zostaly policzone tylko z historii dostepnej przed
odpowiednim punktem czasowym.

## 5. Trening glownego TGN

Najpierw wykonaj krotki test treningu:

```bash
.venv/bin/python train_self_supervised.py \
  -d events_5M \
  --use_memory \
  --prefix tgn-attn-events_5M-smoke \
  --n_epoch 1 \
  --n_runs 1
```

Nastepnie uruchom wlasciwy trening:

```bash
.venv/bin/python train_self_supervised.py \
  -d events_5M \
  --use_memory \
  --prefix tgn-attn-events_5M \
  --n_epoch 50 \
  --n_runs 5
```

Jesli zabraknie pamieci, zmniejsz batch size:

```bash
.venv/bin/python train_self_supervised.py \
  -d events_5M \
  --use_memory \
  --prefix tgn-attn-events_5M-bs100 \
  --bs 100 \
  --n_epoch 50 \
  --n_runs 5
```

Do szybkiej iteracji mozna zaczac od `--n_epoch 10 --n_runs 1`.

## 6. Baselines

Baseline'y nalezy uruchamiac na dokladnie tym samym zbiorze i z podobnym
budzetem epok oraz liczby runow.

### JODIE-like

```bash
.venv/bin/python train_self_supervised.py \
  -d events_5M \
  --use_memory \
  --memory_updater rnn \
  --embedding_module time \
  --prefix jodie_rnn-events_5M \
  --n_epoch 50 \
  --n_runs 5
```

### DyRep-like

```bash
.venv/bin/python train_self_supervised.py \
  -d events_5M \
  --use_memory \
  --memory_updater rnn \
  --dyrep \
  --use_destination_embedding_in_message \
  --prefix dyrep_rnn-events_5M \
  --n_epoch 50 \
  --n_runs 5
```

### TGN bez pamieci

```bash
.venv/bin/python train_self_supervised.py \
  -d events_5M \
  --prefix tgn-no-mem-events_5M \
  --n_epoch 50 \
  --n_runs 5
```

## 7. Supervised training

Na obecnym zbiorze `label` ma wartosc `0.0` dla wszystkich interakcji, dlatego
`train_supervised.py` nie ma jeszcze sensownego celu klasyfikacji.

Przed supervised training trzeba zdefiniowac etykiete, np.:

- typ lub klasa kanalu,
- ryzyko / wiarygodnosc,
- przyszla aktywnosc,
- przyszle wystapienie relacji,
- kategoria propagacji tresci.

Do tego czasu glowna metryka eksperymentu powinna pochodzic z self-supervised
link prediction.

## 8. Weryfikacja wynikow

Artefakty sa zapisywane w:

- `results/*.pkl` - wyniki metryk,
- `saved_models/` - zapisane modele,
- `saved_checkpoints/` - checkpointy,
- `log/` - logi treningu.

Najwazniejsze metryki do porownania:

- `test_ap`,
- `new_node_test_ap`,
- przebieg `val_aps`,
- stabilnosc miedzy `n_runs`,
- czas epoki,
- zuzycie pamieci.

Minimalny odczyt wynikow:

```bash
.venv/bin/python -c "import pickle, glob; \
for p in sorted(glob.glob('results/*.pkl')): \
    r=pickle.load(open(p,'rb')); \
    print(p, 'test_ap=', r.get('test_ap'), 'new_node_test_ap=', r.get('new_node_test_ap'))"
```

## 9. Korekty runtime i kompatybilnosci

Podczas uruchamiania treningu na danych Telegram zidentyfikowano kilka praktycznych
problemow kompatybilnosci.

### PyTorch, CUDA i NVIDIA L4

Blad:

```text
RuntimeError: CUDA error: no kernel image is available for execution on the device
```

oznacza, ze PyTorch widzi CUDA, ale jego binarka nie obsluguje architektury GPU.
Przyklad problematycznej konfiguracji:

```text
GPU: NVIDIA L4
torch: 1.6.0
CUDA runtime PyTorch: 10.2
torch.cuda.is_available(): True
```

Taka wersja PyTorch jest za stara dla NVIDIA L4. Rekomendowana korekta to
zainstalowanie nowszego PyTorch z runtime CUDA 12.x:

```bash
.venv/bin/pip uninstall -y torch torchvision torchaudio
.venv/bin/pip install torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu121
```

Sprawdzenie:

```bash
.venv/bin/python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

### Aktualizacja pamieci TGN

Blad:

```text
AssertionError: Something wrong in how the memory was updated
```

pojawial sie w `model/tgn.py` podczas treningu z `--use_memory`. Oryginalny kod
liczyl aktualizacje pamieci GRU/RNN, nastepnie liczyl te aktualizacje ponownie i
porownywal wyniki asercja `torch.allclose`. Na nowszym GPU oraz przy duzych
wartosciach cech krawedzi taka asercja moze byc zbyt krucha numerycznie.

Korekta w `model/tgn.py`: zamiast przeliczac aktualizacje i porownywac ja z
wartoscia juz policzona, zapisywana jest bezposrednio aktualna, juz wyliczona
wersja pamieci:

```python
self.memory.set_memory(positives, memory[positives])
self.memory.last_update[positives] = last_update[positives]
```

Po tej zmianie smoke test:

```bash
.venv/bin/python train_self_supervised.py \
  -d events_sample \
  --use_memory \
  --prefix tgn-attn-events_sample-smoke \
  --n_epoch 1 \
  --n_runs 1
```

przechodzi do konca.

### Python 3.12 i random.sample

W Pythonie 3.12 `random.sample` nie przyjmuje bezposrednio seta. Jesli pojawia sie:

```text
TypeError: Population must be a sequence. For dicts or sets, use sorted(d).
```

to nalezy probkowac z posortowanej sekwencji:

```python
new_test_node_set = set(random.sample(sorted(test_node_set), int(0.1 * n_total_unique_nodes)))
```

Ta korekta znajduje sie w `utils/data_processing.py`.

## 10. Zalecana kolejnosc eksperymentow

1. `events_sample` - smoke test konwersji i preprocessingu.
2. `events_5M_no_channel` - czystszy temporalnie baseline bez statycznych cech kanalow.
3. `events_5M` - wariant feature-rich z cechami kanalow.
4. Baseline'y: JODIE-like, DyRep-like, TGN bez pamieci.
5. Pelny zbior dopiero po potwierdzeniu stabilnosci na 5M.

## 11. Uwagi koncowe

Relacje `FORWARD` i `SAME_URL` sa obecnie kodowane jako cechy krawedzi i trafiaja
do jednego strumienia interakcji temporalnych. To dobry pierwszy baseline, ale
nie jest to pelny model relacyjny. Jesli typ relacji okaze sie kluczowy, warto
rozwazyc osobne modelowanie relacji albo relacyjny wariant temporal graph modelu.
