#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/prepare_streamlit_runtime.sh [options]

Prepare every runtime artifact needed for full DGX Streamlit testing. Existing
artifacts are detected and skipped. Missing artifacts are generated in the
correct order.

Options:
  --run-streamlit              Run scripts/run_offline_streamlit_test.sh after preparation.
  --replace                    Pass --replace to the Streamlit runner.
  --port <port>                Pass --port to the Streamlit runner. Default: 8501.
  --skip-offline-assets        Do not run scripts/prepare_offline_assets.py.
  --no-verify-load             Pass --no-verify-load to scripts/prepare_offline_assets.py.
  --cpu-index                  Run index embedding with CPU instead of GPU.
  --force-chunks               Rebuild chunk JSONL files even when they exist.
  --force-indexes              Rebuild index directories even when they exist.
  --force-mapping              Rebuild v1/v2 pair mapping files even when they exist.
  --skip-v2-handoff-import     Do not auto-extract handoff/ocr_v2_manual_handoff_*.tar.gz.
  -h, --help                   Show this help.

Default indexing policy follows the DGX runtime decision:
  Streamlit/RAG query embedding: CPU
  SGLang/vLLM large LLM: GPU 0
  batch index/embedding generation in this script: GPU 0
EOF
}

RUN_STREAMLIT=0
REPLACE=0
PORT="${STREAMLIT_PORT:-8501}"
SKIP_OFFLINE_ASSETS=0
NO_VERIFY_LOAD=0
CPU_INDEX=0
FORCE_CHUNKS=0
FORCE_INDEXES=0
FORCE_MAPPING=0
SKIP_V2_HANDOFF_IMPORT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-streamlit)
      RUN_STREAMLIT=1
      shift
      ;;
    --replace)
      REPLACE=1
      shift
      ;;
    --port)
      PORT="${2:?--port requires a value}"
      shift 2
      ;;
    --skip-offline-assets)
      SKIP_OFFLINE_ASSETS=1
      shift
      ;;
    --no-verify-load)
      NO_VERIFY_LOAD=1
      shift
      ;;
    --cpu-index)
      CPU_INDEX=1
      shift
      ;;
    --force-chunks)
      FORCE_CHUNKS=1
      shift
      ;;
    --force-indexes)
      FORCE_INDEXES=1
      shift
      ;;
    --force-mapping)
      FORCE_MAPPING=1
      shift
      ;;
    --skip-v2-handoff-import)
      SKIP_V2_HANDOFF_IMPORT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AI_OPS_ROOT="${AI_OPS_ROOT:-/srv/ai-ops}"
SECRETS_DIR="${SECRETS_DIR:-$AI_OPS_ROOT/secrets/insurance-rag-chatbot}"
PRIVATE_ENV_FILE="${PRIVATE_ENV_FILE:-$SECRETS_DIR/env.sh}"
OFFLINE_ENV_FILE="${OFFLINE_ENV_FILE:-$SECRETS_DIR/offline.env}"
LOG_DIR="${LOG_DIR:-$PROJECT_DIR/logs}"

cd "$PROJECT_DIR"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/prepare_streamlit_runtime_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

log() {
  printf '[prep] %s\n' "$*"
}

need_file() {
  [[ -f "$1" ]]
}

need_dir() {
  [[ -d "$1" ]]
}

run_step() {
  log "RUN: $*"
  "$@"
}

require_path() {
  local path="$1"
  local label="$2"
  if [[ ! -e "$path" ]]; then
    echo "ERROR: missing $label: $path" >&2
    exit 1
  fi
}

if [[ ! -x ".venv/bin/python" ]]; then
  echo "ERROR: project venv is missing: $PROJECT_DIR/.venv" >&2
  exit 1
fi

source .venv/bin/activate

if [[ -f "$PRIVATE_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$PRIVATE_ENV_FILE"
  set +a
fi

export OFFLINE_MODE="${OFFLINE_MODE:-true}"
export HF_MODEL_DOWNLOAD="${HF_MODEL_DOWNLOAD:-false}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-$AI_OPS_ROOT/models/embedding/bge-m3}"
export RERANKER_MODEL="${RERANKER_MODEL:-$AI_OPS_ROOT/models/reranker/bge-reranker-v2-m3}"
export RERANKER_ENABLED="${RERANKER_ENABLED:-false}"

if [[ "$CPU_INDEX" == "1" ]]; then
  export CUDA_VISIBLE_DEVICES=""
  log "Index generation will run on CPU."
else
  export CUDA_VISIBLE_DEVICES="${INDEX_CUDA_VISIBLE_DEVICES:-0}"
  log "Index generation will use CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES."
fi

if [[ "$SKIP_OFFLINE_ASSETS" != "1" ]]; then
  prepare_args=(--root "$AI_OPS_ROOT" --env-path "$OFFLINE_ENV_FILE")
  if [[ "$NO_VERIFY_LOAD" == "1" ]]; then
    prepare_args+=(--no-verify-load)
  fi
  run_step .venv/bin/python scripts/prepare_offline_assets.py "${prepare_args[@]}"
fi

if [[ -f "$OFFLINE_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$OFFLINE_ENV_FILE"
  set +a
  if [[ "$CPU_INDEX" == "1" ]]; then
    export CUDA_VISIBLE_DEVICES=""
  else
    export CUDA_VISIBLE_DEVICES="${INDEX_CUDA_VISIBLE_DEVICES:-0}"
  fi
fi

if [[ "$SKIP_V2_HANDOFF_IMPORT" != "1" && ! -f data/extracted_v2_manual/실무가이드/manifest.json ]]; then
  archive="$(find handoff -maxdepth 1 -type f -name 'ocr_v2_manual_handoff_*.tar.gz' 2>/dev/null | sort | tail -n 1 || true)"
  if [[ -z "$archive" ]]; then
    echo "ERROR: data/extracted_v2_manual is missing and no v2 handoff archive exists under handoff/." >&2
    exit 1
  fi
  first_entry="$(tar -tzf "$archive" | sed -n '1p')"
  log "Importing v2 manual handoff: $archive"
  case "$first_entry" in
    data/*)
      run_step tar -xzf "$archive" -C .
      ;;
    */data/*)
      run_step tar -xzf "$archive" --strip-components=1 -C .
      ;;
    *)
      echo "ERROR: unexpected v2 handoff layout: $first_entry" >&2
      exit 1
      ;;
  esac
fi

require_path "data/extracted/실무가이드/manifest.json" "v1 실무가이드 manifest"
require_path "data/extracted/상담사례집/manifest.json" "v1 상담사례집 manifest"
require_path "data/extracted_v2_manual/실무가이드/manifest.json" "v2 실무가이드 manifest"
require_path "data/extracted_v2_manual/상담사례집/manifest.json" "v2 상담사례집 manifest"

mkdir -p data/processed

if [[ "$FORCE_CHUNKS" == "1" || ! -f data/processed/chunks_v1_original_ocr.jsonl ]]; then
  run_step .venv/bin/python scripts/ingest.py \
    --include-ocr \
    --stage chunks \
    --extracted-root data/extracted \
    --chunks-path data/processed/chunks_v1_original_ocr.jsonl
else
  log "SKIP existing data/processed/chunks_v1_original_ocr.jsonl"
fi

if [[ ! -d data/extracted_v1_rechunked ]]; then
  log "Creating data/extracted_v1_rechunked from data/extracted"
  run_step cp -a data/extracted data/extracted_v1_rechunked
else
  log "SKIP existing data/extracted_v1_rechunked"
fi

if [[ "$FORCE_CHUNKS" == "1" || ! -f data/processed/chunks_v1_rechunked_target16.jsonl ]]; then
  run_step .venv/bin/python scripts/rechunk_v1_sangdam_target16.py \
    --extracted-v1-root data/extracted_v1_rechunked \
    --extracted-v2-root data/extracted_v2_manual \
    --v1-chunks data/processed/chunks_v1_original_ocr.jsonl \
    --rechunked-chunks data/processed/chunks_v1_rechunked_only_sangdam.jsonl \
    --output-chunks data/processed/chunks_v1_rechunked_target16.jsonl \
    --in-place

  if [[ "$FORCE_CHUNKS" == "1" || ! -f data/processed/chunks_v1_rechunked_only_sangdam.jsonl ]]; then
    run_step .venv/bin/python scripts/ingest.py \
      --include-ocr \
      --stage chunks \
      --extracted-root data/extracted_v1_rechunked \
      --chunks-path data/processed/chunks_v1_rechunked_only_sangdam.jsonl
  else
    log "SKIP existing data/processed/chunks_v1_rechunked_only_sangdam.jsonl"
  fi

  run_step .venv/bin/python scripts/rechunk_v1_sangdam_target16.py \
    --extracted-v1-root data/extracted_v1_rechunked \
    --extracted-v2-root data/extracted_v2_manual \
    --v1-chunks data/processed/chunks_v1_original_ocr.jsonl \
    --rechunked-chunks data/processed/chunks_v1_rechunked_only_sangdam.jsonl \
    --output-chunks data/processed/chunks_v1_rechunked_target16.jsonl \
    --in-place
else
  log "SKIP existing data/processed/chunks_v1_rechunked_target16.jsonl"
fi

if [[ "$FORCE_CHUNKS" == "1" || ! -f data/processed/chunks_v2_manual.jsonl ]]; then
  run_step .venv/bin/python scripts/ingest.py \
    --include-ocr \
    --stage chunks \
    --extracted-root data/extracted_v2_manual \
    --chunks-path data/processed/chunks_v2_manual.jsonl
else
  log "SKIP existing data/processed/chunks_v2_manual.jsonl"
fi

if [[ "$FORCE_INDEXES" == "1" || ! -f data/index_v2_manual/bm25.pkl || ! -f data/index_v2_manual/chroma/chroma.sqlite3 ]]; then
  run_step .venv/bin/python scripts/ingest.py \
    --stage index \
    --chunks-path data/processed/chunks_v2_manual.jsonl \
    --index-root data/index_v2_manual
else
  log "SKIP existing data/index_v2_manual"
fi

if [[ "$FORCE_CHUNKS" == "1" || ! -f data/processed/chunks_v1_v2_combined.jsonl ]]; then
  run_step .venv/bin/python scripts/build_ocr_combined_chunks.py \
    --v1-chunks-path data/processed/chunks_v1_rechunked_target16.jsonl \
    --v2-chunks-path data/processed/chunks_v2_manual.jsonl \
    --output-path data/processed/chunks_v1_v2_combined.jsonl
else
  log "SKIP existing data/processed/chunks_v1_v2_combined.jsonl"
fi

if [[ "$FORCE_INDEXES" == "1" || ! -f data/index_v1_v2_combined/bm25.pkl || ! -f data/index_v1_v2_combined/chroma/chroma.sqlite3 ]]; then
  run_step .venv/bin/python scripts/ingest.py \
    --stage index \
    --chunks-path data/processed/chunks_v1_v2_combined.jsonl \
    --index-root data/index_v1_v2_combined
else
  log "SKIP existing data/index_v1_v2_combined"
fi

if [[ "$FORCE_MAPPING" == "1" || ! -f data/mapping/v1_v2_pairs_실무가이드.jsonl || ! -f data/mapping/v1_v2_pairs_상담사례집.jsonl ]]; then
  run_step .venv/bin/python scripts/build_v1_v2_pair_mapping.py --emit-low-confidence-report
else
  log "SKIP existing data/mapping/v1_v2_pairs_*.jsonl"
fi

log "Final runtime artifact check"
required=(
  "data/processed/chunks_v1_original_ocr.jsonl"
  "data/processed/chunks_v1_rechunked_target16.jsonl"
  "data/processed/chunks_v2_manual.jsonl"
  "data/processed/chunks_v1_v2_combined.jsonl"
  "data/index/bm25.pkl"
  "data/index/chroma/chroma.sqlite3"
  "data/index_v2_manual/bm25.pkl"
  "data/index_v2_manual/chroma/chroma.sqlite3"
  "data/index_v1_v2_combined/bm25.pkl"
  "data/index_v1_v2_combined/chroma/chroma.sqlite3"
  "data/index/relational/standard_codes.sqlite"
  "data/mapping/v1_v2_pairs_실무가이드.jsonl"
  "data/mapping/v1_v2_pairs_상담사례집.jsonl"
)

for path in "${required[@]}"; do
  require_path "$path" "$path"
  log "OK $path"
done

log "Line counts"
wc -l \
  data/processed/chunks_v1_original_ocr.jsonl \
  data/processed/chunks_v1_rechunked_target16.jsonl \
  data/processed/chunks_v2_manual.jsonl \
  data/processed/chunks_v1_v2_combined.jsonl \
  data/mapping/v1_v2_pairs_실무가이드.jsonl \
  data/mapping/v1_v2_pairs_상담사례집.jsonl

log "Preparation complete. Log: $LOG_FILE"

if [[ "$RUN_STREAMLIT" == "1" ]]; then
  runner_args=(--skip-asset-prep --port "$PORT")
  if [[ "$REPLACE" == "1" ]]; then
    runner_args+=(--replace)
  fi
  log "Starting Streamlit via scripts/run_offline_streamlit_test.sh ${runner_args[*]}"
  exec bash scripts/run_offline_streamlit_test.sh "${runner_args[@]}"
fi
