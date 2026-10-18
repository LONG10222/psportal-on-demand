#!/bin/zsh
set -eu
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
python_bin="$project_dir/../../work/desktop-env/bin/python"
if [[ ! -x "$python_bin" ]]; then
  print -u2 '缺少本机开发运行环境，请参阅 START-HERE.md / Local runtime missing; see START-HERE.md'
  exit 1
fi
exec "$python_bin" "$project_dir/launch-local.py"
