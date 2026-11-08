#!/bin/zsh
# Double-click on macOS, or run ./start-ui.command from the repository.
set -eu
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print 'Создайте окружение Python 3.11+ по инструкции docs/ui-workspace.md.'
  exit 1
fi
ui_db=outputs/product-demo/cqa-1.2.1.sqlite3
if [[ ! -f $ui_db && -f data/workspace.sqlite3 ]]; then
  ui_db=data/workspace.sqlite3
fi
ui_args=(--port 8787 --db "${CQA_DB:-$ui_db}" --settings "${CQA_SETTINGS:-config/settings.product.json}")
if [[ -f data/dev.json ]]; then
  ui_args+=(--dataset data/dev.json)
  [[ ! -f results/dev/results.json ]] || ui_args+=(--baseline results/dev/results.json)
fi
[[ ! -d data/audio ]] || ui_args+=(--audio-dir data/audio)
print 'CQA: откройте http://127.0.0.1:8787 в браузере. Остановка: Ctrl+C.'
exec .venv/bin/python -m cqa.web "${ui_args[@]}"
