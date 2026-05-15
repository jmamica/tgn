# Events Parquet Converter

`events_parquet_to_csv.py` converts parquet files from `data_raw/events/` to the raw CSV format expected by the existing TGN preprocessing flow, analogous to `reddit.csv` and `wikipedia.csv`.

It also uses optional preprocessing artifacts from `data_raw/preprocess/` when they are present.

## Input

By default the converter reads:

```bash
data_raw/events/events_v1.parquet
```

The detected schema is:

```text
src, dst, timestamp, event_type, dt_bucket, has_media, url_count_bucket,
char_count_bucket, url_hash, domain
```

The converter maps:

```text
src -> user
dst -> item
timestamp -> timestamp
label -> state_label, default 0.0
```

Numeric columns not used as endpoints/timestamp are written as edge features. `event_type` is one-hot encoded by default.

## Preprocess Artifacts

When `data_raw/preprocess/` exists, the converter uses:

```text
data_raw/preprocess/channel_filter_v1.csv
data_raw/preprocess/channel_stats.parquet
data_raw/preprocess/style_features.parquet
```

`channel_filter_v1.csv` is applied by default: only events where both `src` and `dst` have
`kept=True` are exported. Disable this with:

```bash
python3 utils/events_parquet_to_csv.py --no-channel-filter
```

`channel_stats.parquet` and `style_features.parquet` are appended by default as edge features for
both endpoints. Feature names are prefixed internally as `src_*` and `dst_*` before they are written
to numeric feature columns in the raw CSV. Disable this with:

```bash
python3 utils/events_parquet_to_csv.py --no-channel-features
```

Use another preprocessing directory with:

```bash
python3 utils/events_parquet_to_csv.py --preprocess-dir path/to/preprocess
```

## Output Format

The output CSV has the same raw layout as the public JODIE datasets:

```text
user,item,timestamp,state_label,feature_0,feature_1,...
```

By default the raw converted CSV is written under `data_raw/`. This keeps source and intermediate
conversion output separate from the `data/` directory consumed by training.

This file can then be passed to `utils/preprocess_data.py`, which creates:

```text
data/ml_<name>.csv
data/ml_<name>.npy
data/ml_<name>_node.npy
```

## Basic Usage

Convert the full `events_v1.parquet` file:

```bash
python3 utils/events_parquet_to_csv.py --sort
python3 utils/preprocess_data.py --data events --input-dir data_raw --output-dir data --bipartite
```

## Using Split Windows

The `splits_*.json` files contain timestamp bounds. Use `--split-file` to export only a selected window:

```bash
python3 utils/events_parquet_to_csv.py \
  --split-file data_raw/events/splits_2_2M_v1.json \
  --output data_raw/events_2_2M.csv \
  --sort

python3 utils/preprocess_data.py \
  --data events_2_2M \
  --input-dir data_raw \
  --output-dir data \
  --bipartite
```

Available split files include:

```text
data_raw/events/splits_v1.json
data_raw/events/splits_10M_v1.json
data_raw/events/splits_5M_v1.json
data_raw/events/splits_2_2M_v1.json
```

## Node Encoding Modes

Default mode encodes `src` and `dst` separately, which is compatible with `--bipartite` preprocessing:

```bash
python3 utils/events_parquet_to_csv.py --output data_raw/events.csv --sort
python3 utils/preprocess_data.py --data events --input-dir data_raw --output-dir data --bipartite
```

If `src` and `dst` should represent one shared node space, use:

```bash
python3 utils/events_parquet_to_csv.py \
  --shared-node-space \
  --output data_raw/events.csv \
  --sort

python3 utils/preprocess_data.py --data events --input-dir data_raw --output-dir data
```

## Smoke Test

For a quick schema check and small sample:

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

If channel filtering is enabled, a small sample can contain fewer than `--max-rows` rows because the
limit is applied while reading the parquet file, then rows outside `channel_filter_v1.csv` are removed.

## Custom Columns

If a parquet file uses different column names, override them explicitly:

```bash
python3 utils/events_parquet_to_csv.py \
  --input custom.parquet \
  --source-col source_id \
  --destination-col target_id \
  --timestamp-col event_time \
  --label-col label \
  --output data_raw/custom_events.csv
```

Feature columns can also be selected manually:

```bash
python3 utils/events_parquet_to_csv.py \
  --feature-cols dt_bucket has_media \
  --categorical-feature-cols event_type \
  --output data_raw/events.csv
```

Pass `--categorical-feature-cols` with no values to disable categorical features.

## Requirements

The converter requires:

```text
pandas
numpy
pyarrow or another pandas-compatible parquet engine
```

The project README already requires `pandas` and `numpy`; install `pyarrow` if parquet support is missing.
