#!/bin/bash
set -e

# Load env vars if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

echo "▶ Running: score_agent.py"
python score_agent.py || true

echo "▶ Running: analyze_trends.py"
python analyze_trends.py

echo "▶ Running: build_ui_state.py"
python build_ui_state.py

echo "✅ MVP refresh complete"
