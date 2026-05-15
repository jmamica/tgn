import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE_CANDIDATES = (
  'source', 'src', 'src_id', 'source_id', 'from', 'from_id', 'u', 'user', 'user_id',
  'sender', 'sender_id'
)
DESTINATION_CANDIDATES = (
  'destination', 'dst', 'dst_id', 'destination_id', 'target', 'target_id', 'to',
  'to_id', 'v', 'item', 'item_id', 'receiver', 'receiver_id'
)
TIMESTAMP_CANDIDATES = (
  'timestamp', 'ts', 'time', 'datetime', 'date', 'created_at', 'event_time',
  'unix_ts', 'unixts'
)
LABEL_CANDIDATES = ('label', 'state_label', 'target_label', 'y')


def parse_args():
  parser = argparse.ArgumentParser(
    'Convert parquet event data to the raw TGN csv format used by wikipedia.csv/reddit.csv')
  parser.add_argument('--events-dir', type=Path, default=Path('data_raw/events'),
                      help='Directory containing parquet event files')
  parser.add_argument('--preprocess-dir', type=Path, default=Path('data_raw/preprocess'),
                      help='Directory containing channel_filter_v1.csv and channel feature parquet files')
  parser.add_argument('--input', nargs='+', default=None,
                      help='Parquet files to convert. Defaults to events_v1.parquet when present, '
                           'otherwise all *.parquet files in events-dir')
  parser.add_argument('--output', type=Path, default=Path('data_raw/events.csv'),
                      help='Output csv path consumed later by utils/preprocess_data.py')
  parser.add_argument('--source-col', default=None, help='Source node column')
  parser.add_argument('--destination-col', default=None, help='Destination node column')
  parser.add_argument('--timestamp-col', default=None, help='Timestamp column')
  parser.add_argument('--label-col', default=None,
                      help='Optional state label column. Defaults to zeros if omitted/not found')
  parser.add_argument('--feature-cols', nargs='*', default=None,
                      help='Columns to write as edge features. Defaults to numeric columns not used '
                           'as source/destination/timestamp/label')
  parser.add_argument('--categorical-feature-cols', nargs='*', default=None,
                      help='Categorical columns to one-hot encode as edge features. Defaults to '
                           'event_type when present. Pass the flag with no values to disable')
  parser.add_argument('--split-file', type=Path, default=None,
                      help='Optional split json with t0/t3 bounds used to filter the time window')
  parser.add_argument('--no-channel-filter', action='store_true',
                      help='Do not filter src/dst channels with data_raw/preprocess/channel_filter_v1.csv')
  parser.add_argument('--no-channel-features', action='store_true',
                      help='Do not append src/dst features from data_raw/preprocess/channel_stats.parquet '
                           'and data_raw/preprocess/style_features.parquet')
  parser.add_argument('--add-relation-feature', action='store_true',
                      help='Append one-hot relation features when multiple parquet files are used')
  parser.add_argument('--shared-node-space', action='store_true',
                      help='Encode sources and destinations into one shared id space. Leave disabled '
                           'for bipartite data converted like wikipedia.csv/reddit.csv')
  parser.add_argument('--sort', action='store_true',
                      help='Sort interactions by timestamp before writing')
  parser.add_argument('--max-rows', type=int, default=None,
                      help='Optional row limit per parquet file, useful for smoke tests')
  parser.add_argument('--print-schema', action='store_true',
                      help='Print columns and inferred mappings before conversion')
  return parser.parse_args()


def resolve_inputs(events_dir, inputs):
  if inputs is None:
    combined_events = events_dir / 'events_v1.parquet'
    paths = [combined_events] if combined_events.exists() else sorted(events_dir.glob('*.parquet'))
  else:
    paths = [Path(path) for path in inputs]
    paths = [path if path.is_absolute() else events_dir / path for path in paths]

  paths = [path for path in paths if not path.name.endswith(':Zone.Identifier')]
  if not paths:
    raise ValueError('No parquet files found to convert')
  missing = [str(path) for path in paths if not path.exists()]
  if missing:
    raise FileNotFoundError('Missing parquet files: {}'.format(', '.join(missing)))
  return paths


def first_existing(columns, candidates, explicit=None, required=True, name='column'):
  if explicit:
    if explicit not in columns:
      raise ValueError('{} {!r} is not present. Available columns: {}'.format(
        name, explicit, ', '.join(columns)))
    return explicit

  lower_to_original = {column.lower(): column for column in columns}
  for candidate in candidates:
    if candidate.lower() in lower_to_original:
      return lower_to_original[candidate.lower()]

  if required:
    raise ValueError('Could not infer {}. Available columns: {}'.format(
      name, ', '.join(columns)))
  return None


def normalize_timestamp(series):
  if np.issubdtype(series.dtype, np.datetime64):
    return series.astype('int64') / 1e9
  return pd.to_numeric(series, errors='raise').astype(float)


def encode_ids(series):
  codes, uniques = pd.factorize(series, sort=True)
  return codes.astype(int), uniques


def encode_endpoints(edges, shared_node_space):
  if shared_node_space:
    endpoints = pd.concat([edges['_raw_u'], edges['_raw_i']], ignore_index=True)
    codes, _ = pd.factorize(endpoints, sort=True)
    split_at = len(edges)
    edges['user'] = codes[:split_at].astype(int)
    edges['item'] = codes[split_at:].astype(int)
  else:
    edges['user'], _ = encode_ids(edges['_raw_u'])
    edges['item'], _ = encode_ids(edges['_raw_i'])


def choose_feature_columns(df, used_columns, requested_columns):
  if requested_columns is not None:
    missing = [column for column in requested_columns if column not in df.columns]
    if missing:
      raise ValueError('Missing feature columns: {}'.format(', '.join(missing)))
    return requested_columns

  feature_columns = []
  for column in df.columns:
    if column in used_columns:
      continue
    if pd.api.types.is_numeric_dtype(df[column]):
      feature_columns.append(column)
  return feature_columns


def choose_categorical_feature_columns(df, used_columns, requested_columns):
  if requested_columns is not None:
    missing = [column for column in requested_columns if column not in df.columns]
    if missing:
      raise ValueError('Missing categorical feature columns: {}'.format(', '.join(missing)))
    return requested_columns

  return ['event_type'] if 'event_type' in df.columns and 'event_type' not in used_columns else []


def load_split_bounds(split_file):
  if split_file is None:
    return None

  with open(split_file) as f:
    split = json.load(f)

  if 't0' not in split or 't3' not in split:
    raise ValueError('Split file must contain t0 and t3: {}'.format(split_file))
  return split['t0'], split['t3']


def filter_time_window(edges, features, split_bounds):
  if split_bounds is None:
    return edges, features

  t0, t3 = split_bounds
  mask = edges['timestamp'].between(t0, t3, inclusive='both')
  return edges.loc[mask].reset_index(drop=True), features.loc[mask].reset_index(drop=True)


def load_allowed_channels(preprocess_dir, disabled=False):
  if disabled:
    return None

  path = preprocess_dir / 'channel_filter_v1.csv'
  if not path.exists():
    return None

  df = pd.read_csv(path)
  if 'channel_id' not in df.columns or 'kept' not in df.columns:
    raise ValueError('{} must contain channel_id and kept columns'.format(path))
  if pd.api.types.is_bool_dtype(df['kept']):
    kept_mask = df['kept']
  else:
    kept_mask = df['kept'].astype(str).str.lower().isin(('true', '1', 'yes'))
  kept = df[kept_mask]
  return set(kept['channel_id'])


def load_channel_features(preprocess_dir, disabled=False):
  if disabled:
    return None

  paths = [
    preprocess_dir / 'channel_stats.parquet',
    preprocess_dir / 'style_features.parquet',
  ]
  frames = []
  used_columns = {'channel_id'}

  for path in paths:
    if not path.exists():
      continue

    df = pd.read_parquet(path)
    if 'channel_id' not in df.columns:
      raise ValueError('{} must contain channel_id column'.format(path))

    selected_columns = ['channel_id']
    for column in df.columns:
      if column == 'channel_id' or column in used_columns:
        continue
      if pd.api.types.is_numeric_dtype(df[column]):
        selected_columns.append(column)
        used_columns.add(column)
    frames.append(df[selected_columns])

  if not frames:
    return None

  features = frames[0]
  for frame in frames[1:]:
    features = features.merge(frame, on='channel_id', how='outer')

  return features.set_index('channel_id').fillna(0.0)


def apply_allowed_channels(df, source_col, destination_col, allowed_channels):
  if allowed_channels is None:
    return df

  mask = df[source_col].isin(allowed_channels) & df[destination_col].isin(allowed_channels)
  return df.loc[mask].reset_index(drop=True)


def lookup_channel_features(channel_features, ids, prefix):
  if channel_features is None:
    return None

  matched = channel_features.reindex(ids).reset_index(drop=True).fillna(0.0)
  matched.columns = ['{}_{}'.format(prefix, column) for column in matched.columns]
  return matched


def read_parquet(path, max_rows, split_bounds):
  filters = None
  if split_bounds is not None:
    t0, t3 = split_bounds
    filters = [('timestamp', '>=', t0), ('timestamp', '<=', t3)]

  if max_rows is None:
    return pd.read_parquet(path, filters=filters)
  if filters is not None:
    return pd.read_parquet(path, filters=filters).head(max_rows)

  try:
    import pyarrow.parquet as pq
  except ImportError:
    return pd.read_parquet(path, filters=filters).head(max_rows)

  parquet_file = pq.ParquetFile(path)
  tables = []
  rows_left = max_rows
  for row_group in range(parquet_file.num_row_groups):
    table = parquet_file.read_row_group(row_group)
    if table.num_rows > rows_left:
      table = table.slice(0, rows_left)
    tables.append(table)
    rows_left -= table.num_rows
    if rows_left <= 0:
      break

  if not tables:
    return pd.DataFrame()
  return pd.concat([table.to_pandas() for table in tables], ignore_index=True)


def load_edges(path, args, allowed_channels, channel_features):
  df = read_parquet(path, args.max_rows, args.split_bounds)

  columns = list(df.columns)
  source_col = first_existing(
    columns, SOURCE_CANDIDATES, args.source_col, name='source column')
  destination_col = first_existing(
    columns, DESTINATION_CANDIDATES, args.destination_col, name='destination column')
  timestamp_col = first_existing(
    columns, TIMESTAMP_CANDIDATES, args.timestamp_col, name='timestamp column')
  label_col = first_existing(
    columns, LABEL_CANDIDATES, args.label_col, required=False, name='label column')

  df = apply_allowed_channels(df, source_col, destination_col, allowed_channels)

  if args.print_schema:
    print('\n{}'.format(path))
    print('columns: {}'.format(', '.join(columns)))
    print('source={}, destination={}, timestamp={}, label={}'.format(
      source_col, destination_col, timestamp_col, label_col or '<zeros>'))

  used_columns = {source_col, destination_col, timestamp_col}
  if label_col:
    used_columns.add(label_col)

  feature_columns = choose_feature_columns(df, used_columns, args.feature_cols)
  categorical_feature_columns = choose_categorical_feature_columns(
    df, used_columns, args.categorical_feature_cols)
  if args.print_schema:
    print('features: {}'.format(', '.join(feature_columns) if feature_columns else '<zero>'))
    print('categorical features: {}'.format(
      ', '.join(categorical_feature_columns) if categorical_feature_columns else '<none>'))

  out = pd.DataFrame()
  out['_raw_u'] = df[source_col]
  out['_raw_i'] = df[destination_col]
  out['timestamp'] = normalize_timestamp(df[timestamp_col])
  out['state_label'] = pd.to_numeric(df[label_col], errors='raise') if label_col else 0.0

  if feature_columns:
    features = df[feature_columns].apply(pd.to_numeric, errors='coerce').fillna(0.0)
  else:
    features = pd.DataFrame({'feature_0': np.zeros(len(df), dtype=float)})
  features.columns = ['feature_{}'.format(i) for i in range(features.shape[1])]

  for column in categorical_feature_columns:
    encoded = pd.get_dummies(df[column].fillna('<missing>'), prefix=column, dtype=float)
    features = pd.concat([features.reset_index(drop=True), encoded.reset_index(drop=True)], axis=1)

  src_features = lookup_channel_features(channel_features, df[source_col], 'src')
  dst_features = lookup_channel_features(channel_features, df[destination_col], 'dst')
  for channel_side_features in (src_features, dst_features):
    if channel_side_features is not None:
      features = pd.concat(
        [features.reset_index(drop=True), channel_side_features.reset_index(drop=True)],
        axis=1)

  return out, features


def append_relation_features(feature_frames):
  relation_count = len(feature_frames)
  result = []
  for relation_id, features in enumerate(feature_frames):
    relation_features = np.zeros((len(features), relation_count), dtype=float)
    relation_features[:, relation_id] = 1.0
    relation_df = pd.DataFrame(
      relation_features,
      columns=['relation_{}'.format(i) for i in range(relation_count)])
    result.append(pd.concat([features.reset_index(drop=True), relation_df], axis=1))
  return result


def convert(args):
  paths = resolve_inputs(args.events_dir, args.input)
  args.split_bounds = load_split_bounds(args.split_file)
  allowed_channels = load_allowed_channels(args.preprocess_dir, args.no_channel_filter)
  channel_features = load_channel_features(args.preprocess_dir, args.no_channel_features)

  edge_frames = []
  feature_frames = []
  for path in paths:
    edges, features = load_edges(path, args, allowed_channels, channel_features)
    edges, features = filter_time_window(edges, features, args.split_bounds)
    edge_frames.append(edges)
    feature_frames.append(features)

  if args.add_relation_feature and len(feature_frames) > 1:
    feature_frames = append_relation_features(feature_frames)

  edges = pd.concat(edge_frames, ignore_index=True)
  features = pd.concat(feature_frames, ignore_index=True).fillna(0.0)

  encode_endpoints(edges, args.shared_node_space)

  output = pd.concat(
    [edges[['user', 'item', 'timestamp', 'state_label']].reset_index(drop=True),
     features.reset_index(drop=True)],
    axis=1)

  if args.sort:
    output = output.sort_values('timestamp', kind='mergesort').reset_index(drop=True)

  args.output.parent.mkdir(parents=True, exist_ok=True)
  output.to_csv(args.output, index=False)
  print('Wrote {} interactions to {}'.format(len(output), args.output))
  bipartite_flag = '' if args.shared_node_space else ' --bipartite'
  print('Next: python3 utils/preprocess_data.py --data {} --input-dir {} --output-dir data{}'.format(
    args.output.stem, args.output.parent, bipartite_flag))


if __name__ == '__main__':
  convert(parse_args())
