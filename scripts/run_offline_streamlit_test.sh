#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/run_offline_streamlit_test.sh [options]

Options:
  --port <port>                  Streamlit port. Default: 8501
  --host <host>                  Streamlit bind host. Default: 127.0.0.1
  --replace                      Stop an existing insurance Streamlit process before launch.
  --skip-asset-prep              Do not run scripts/prepare_offline_assets.py.
  --allow-missing-ocr-indexes    Start even if v2/combined OCR indexes are not ready.
  --no-verify-load               Pass --no-verify-load to prepare_offline_assets.py.
  -h, --help                     Show this help.

Default behavior is strict enough for full local/offline feature testing:
offline assets are prepared/verified, OCR indexes are required, and Streamlit is
started with offline runtime environment variables.
EOF
}

PORT="${STREAMLIT_PORT:-8501}"
HOST="${STREAMLIT_HOST:-127.0.0.1}"
REPLACE=0
SKIP_ASSET_PREP=0
ALLOW_MISSING_OCR_INDEXES=0
NO_VERIFY_LOAD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="${2:?--port requires a value}"
      shift 2
      ;;
    --host)
      HOST="${2:?--host requires a value}"
      shift 2
      ;;
    --replace)
      REPLACE=1
      shift
      ;;
    --skip-asset-prep)
      SKIP_ASSET_PREP=1
      shift
      ;;
    --allow-missing-ocr-indexes)
      ALLOW_MISSING_OCR_INDEXES=1
      shift
      ;;
    --no-verify-load)
      NO_VERIFY_LOAD=1
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

if [[ "$SKIP_ASSET_PREP" != "1" ]]; then
  PREPARE_ARGS=(--root "$AI_OPS_ROOT" --env-path "$OFFLINE_ENV_FILE")
  if [[ "$NO_VERIFY_LOAD" == "1" ]]; then
    PREPARE_ARGS+=(--no-verify-load)
  fi
  echo "[1/5] Preparing offline assets under $AI_OPS_ROOT"
  .venv/bin/python scripts/prepare_offline_assets.py "${PREPARE_ARGS[@]}"
fi

if [[ -f "$OFFLINE_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$OFFLINE_ENV_FILE"
  set +a
fi

export OFFLINE_MODE="${OFFLINE_MODE:-true}"
export HF_MODEL_DOWNLOAD="${HF_MODEL_DOWNLOAD:-false}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-$AI_OPS_ROOT/models/embedding/bge-m3}"
export RERANKER_MODEL="${RERANKER_MODEL:-$AI_OPS_ROOT/models/reranker/bge-reranker-v2-m3}"
export GRAPH_ENABLED="${GRAPH_ENABLED:-true}"
export GRAPH_INDEX_PATH="${GRAPH_INDEX_PATH:-$PROJECT_DIR/data/index/graph/insurance_graph.sqlite}"
export GRAPH_CONTEXT_TOP_K="${GRAPH_CONTEXT_TOP_K:-20}"
export GRAPH_CONTEXT_MAX_CHARS="${GRAPH_CONTEXT_MAX_CHARS:-5000}"
export SGLANG_BASE_URL="${SGLANG_BASE_URL:-http://127.0.0.1:30000/v1}"
export SGLANG_API_KEY="${SGLANG_API_KEY:-EMPTY}"
export SGLANG_DEFAULT_MODEL="${SGLANG_DEFAULT_MODEL:-qwen3-30b-a3b-instruct-2507-fp8}"
export SGLANG_CANDIDATE_MODELS="${SGLANG_CANDIDATE_MODELS:-qwen3-30b-a3b-instruct-2507-fp8,gpt-oss-20b}"
export SGLANG_STRICT_AVAILABLE_MODELS="${SGLANG_STRICT_AVAILABLE_MODELS:-false}"
export SGLANG_ENABLE_APP_SWITCH="${SGLANG_ENABLE_APP_SWITCH:-true}"
export SGLANG_SWITCH_SCRIPT="${SGLANG_SWITCH_SCRIPT:-$AI_OPS_ROOT/bin/switch-sglang-model}"
export SGLANG_CUDA_VISIBLE_DEVICES="${SGLANG_CUDA_VISIBLE_DEVICES:-0}"
export VLLM_BASE_URL="${VLLM_BASE_URL:-http://127.0.0.1:30001/v1}"
export VLLM_API_KEY="${VLLM_API_KEY:-EMPTY}"
export VLLM_DEFAULT_MODEL="${VLLM_DEFAULT_MODEL:-nemotron-3-nano-30b-a3b-nvfp4}"
export VLLM_CANDIDATE_MODELS="${VLLM_CANDIDATE_MODELS:-nemotron-3-nano-30b-a3b-nvfp4,gemma-4-26b-a4b-nvfp4}"
export VLLM_STRICT_AVAILABLE_MODELS="${VLLM_STRICT_AVAILABLE_MODELS:-false}"
export VLLM_ENABLE_APP_SWITCH="${VLLM_ENABLE_APP_SWITCH:-true}"
export VLLM_SWITCH_SCRIPT="${VLLM_SWITCH_SCRIPT:-$AI_OPS_ROOT/bin/switch-vllm-model}"
export VLLM_CUDA_VISIBLE_DEVICES="${VLLM_CUDA_VISIBLE_DEVICES:-0}"
export LOCAL_LLM_PROVIDER="${LOCAL_LLM_PROVIDER:-sglang}"
export ALLOW_OLLAMA="${ALLOW_OLLAMA:-true}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-exaone3.5:7.8b}"
export OLLAMA_CANDIDATE_MODELS="${OLLAMA_CANDIDATE_MODELS:-exaone3.5:7.8b}"
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"
export TRANSFORMERS_VERBOSITY="${TRANSFORMERS_VERBOSITY:-error}"

if [[ "${FORCE_GPU:-0}" != "1" ]]; then
  export CUDA_VISIBLE_DEVICES=""
fi

missing=0
require_file() {
  local path="$1"
  local label="$2"
  if [[ -e "$path" ]]; then
    echo "  OK      $label: $path"
  else
    echo "  MISSING $label: $path" >&2
    missing=1
  fi
}

echo "[2/5] Checking offline runtime files"
require_file "$EMBEDDING_MODEL/config.json" "embedding config"
require_file "$RERANKER_MODEL/config.json" "reranker config"
require_file "$AI_OPS_ROOT/llm/models/gpt-oss-20b/config.json" "SGLang gpt-oss model"
require_file "$AI_OPS_ROOT/llm/templates/gpt_oss_harmony.jinja" "GPT-OSS chat template"
require_file "$AI_OPS_ROOT/llm/models/gemma-4-26b-a4b-nvfp4/config.json" "Gemma4 model"
require_file "$AI_OPS_ROOT/llm/models/qwen3-30b-a3b-instruct-2507-fp8/config.json" "Qwen3 FP8 model"
require_file "$AI_OPS_ROOT/llm/models/qwen3-30b-a3b-instruct-2507-fp8/chat_template.jinja" "Qwen3 chat template"
require_file "$AI_OPS_ROOT/llm/models/nemotron-3-nano-30b-a3b-nvfp4/config.json" "Nemotron 3 Nano model"
require_file "$SGLANG_SWITCH_SCRIPT" "SGLang switch script"
require_file "$VLLM_SWITCH_SCRIPT" "vLLM switch script"
require_file "data/index/bm25.pkl" "default BM25"
require_file "data/index/chroma/chroma.sqlite3" "default Chroma"
require_file "data/processed/chunks.jsonl" "default chunks"
require_file "data/index/relational/standard_codes.sqlite" "standard code DB"
if [[ "$GRAPH_ENABLED" == "true" ]]; then
  require_file "$GRAPH_INDEX_PATH" "GraphDB SQLite index"
fi

if [[ "$ALLOW_MISSING_OCR_INDEXES" == "1" ]]; then
  echo "  WARN    OCR v2/combined index checks are relaxed by --allow-missing-ocr-indexes"
else
  require_file "data/index_v2_manual/bm25.pkl" "v2 manual BM25"
  require_file "data/index_v2_manual/chroma/chroma.sqlite3" "v2 manual Chroma"
  require_file "data/processed/chunks_v2_manual.jsonl" "v2 manual chunks"
  require_file "data/index_v1_v2_combined/bm25.pkl" "v1/v2 combined BM25"
  require_file "data/index_v1_v2_combined/chroma/chroma.sqlite3" "v1/v2 combined Chroma"
  require_file "data/processed/chunks_v1_v2_combined.jsonl" "v1/v2 combined chunks"
  require_file "data/mapping/v1_v2_pairs_실무가이드.jsonl" "pair mapping silmu"
  require_file "data/mapping/v1_v2_pairs_상담사례집.jsonl" "pair mapping sangdam"
fi

if [[ "$missing" == "1" ]]; then
  cat >&2 <<'EOF'

ERROR: Required offline test assets are missing.
If only OCR v2/combined modes are missing and you want to test the default index
first, rerun with --allow-missing-ocr-indexes.
EOF
  exit 1
fi

echo "[3/5] Checking local provider endpoints"
if command -v curl >/dev/null 2>&1; then
  if curl -fsS "${SGLANG_BASE_URL%/}/models" >/dev/null 2>&1; then
    echo "  OK      SGLang endpoint responds: $SGLANG_BASE_URL"
  else
    echo "  INFO    SGLang endpoint is not active yet. Login-time model selection can start it."
  fi
  if curl -fsS "${VLLM_BASE_URL%/}/models" >/dev/null 2>&1; then
    echo "  OK      vLLM endpoint responds: $VLLM_BASE_URL"
  else
    echo "  INFO    vLLM endpoint is not active yet. Login-time model selection can start it."
  fi
  if curl -fsS "${OLLAMA_HOST%/}/api/tags" >/dev/null 2>&1; then
    echo "  OK      Ollama endpoint responds: $OLLAMA_HOST"
  else
    echo "  WARN    Ollama endpoint is not active. SGLang/vLLM testing can still proceed."
  fi
fi

if command -v ss >/dev/null 2>&1 && ss -tln "( sport = :$PORT )" | grep -q ":$PORT"; then
  if [[ "$REPLACE" == "1" ]]; then
    echo "[4/5] Replacing existing process on port $PORT"
    mapfile -t port_pids < <(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
    if [[ "${#port_pids[@]}" -eq 0 ]]; then
      echo "ERROR: port $PORT is in use, but no listener PID could be resolved." >&2
      echo "Check with: lsof -i :$PORT" >&2
      exit 1
    fi
    for pid in "${port_pids[@]}"; do
      echo "  stopping PID $pid on port $PORT"
      kill "$pid" 2>/dev/null || {
        echo "ERROR: failed to stop PID $pid. If it belongs to another user, run: sudo kill -9 $pid" >&2
        exit 1
      }
    done
    sleep 2
    if command -v ss >/dev/null 2>&1 && ss -tln "( sport = :$PORT )" | grep -q ":$PORT"; then
      echo "ERROR: port $PORT is still in use after replace attempt." >&2
      echo "Check with: lsof -i :$PORT" >&2
      exit 1
    fi
  else
    echo "ERROR: port $PORT is already in use. Rerun with --replace or choose --port <other>." >&2
    exit 1
  fi
else
  echo "[4/5] Port $PORT is free"
fi

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/offline_streamlit_test_$(date +%Y%m%d_%H%M%S).log"

cat <<EOF
[5/5] Starting Streamlit offline test server
  URL from DGX shell: http://$HOST:$PORT
  Mac tunnel command: ssh -L $PORT:localhost:$PORT ai-hang@100.88.5.57
  Mac browser URL:    http://localhost:$PORT
  Log file:           $LOG_FILE
EOF

.venv/bin/streamlit run src/ui/streamlit_app.py \
  --server.address "$HOST" \
  --server.port "$PORT" \
  --server.headless true \
  2>&1 | tee "$LOG_FILE"
