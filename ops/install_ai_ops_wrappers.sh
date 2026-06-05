#!/usr/bin/env bash

set -euo pipefail

AI_OPS_ROOT="${AI_OPS_ROOT:-/srv/ai-ops}"
TARGET_DIR="${AI_OPS_BIN_DIR:-$AI_OPS_ROOT/bin}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/bin"

mkdir -p "$TARGET_DIR"

for name in \
  insurance-rag-common \
  insurance-rag-prepare \
  insurance-rag-up \
  insurance-rag-status \
  insurance-rag-desktop-launcher \
  prepare-llm-model-assets \
  switch-sglang-model \
  switch-vllm-model; do
  install -m 0755 "$SOURCE_DIR/$name" "$TARGET_DIR/$name"
  echo "installed: $TARGET_DIR/$name"
done

DESKTOP_DIR="${INSURANCE_RAG_DESKTOP_DIR:-$HOME/Desktop}"
DESKTOP_SOURCE="$SCRIPT_DIR/desktop/insurance-rag-chatbot.desktop"
if [[ -d "$DESKTOP_DIR" && -f "$DESKTOP_SOURCE" ]]; then
  DESKTOP_TARGET="$DESKTOP_DIR/신한EZ손해보험 보상지원 AI 챗봇.desktop"
  install -m 0755 "$DESKTOP_SOURCE" "$DESKTOP_TARGET"
  if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_TARGET" metadata::trusted true 2>/dev/null || true
  fi
  echo "installed: $DESKTOP_TARGET"
fi

cat <<EOF

Installed insurance RAG 1.0 wrappers.

Desktop launcher:
  $TARGET_DIR/insurance-rag-desktop-launcher

Start app:
  $TARGET_DIR/insurance-rag-up

Check status:
  $TARGET_DIR/insurance-rag-status

Prepare or rebuild missing runtime artifacts:
  $TARGET_DIR/insurance-rag-prepare --build-missing

Prepare LLM runtime assets:
  $TARGET_DIR/prepare-llm-model-assets
EOF
