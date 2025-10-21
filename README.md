## Kharkov-1926 — Document Processing Pipeline

LLM-powered pipeline and web UI for extracting structured data from 1926 census forms. The app pairs two page images, crops relevant regions, calls a vision-language model (Qwen3-VL-8B-Instruct-FP8 via vLLM), and returns normalized results. A modern web UI supports drag-and-drop, batch mode, overlays, and downloads.

### Features
- Vision-Language extraction with vLLM (OpenAI-compatible API)
- Single pair and batch processing modes
- Sidebar options: padding, overlays, initials enforcement
- Result JSON with variant detection, crops, and final fields
- Docker-first setup; optional local development

### Tech Stack
- Web: Python 3.10, Flask, Bootstrap 5
- LLM serving: vLLM (OpenAI-compatible endpoints)
- Model: `Qwen/Qwen3-VL-8B-Instruct-FP8`
- Containerization: Docker, Docker Compose

---

## Quick Start (Docker Compose)

Prerequisites:
- Docker and Docker Compose (v2 recommended)
- NVIDIA GPU with CUDA support (tested on RTX 4080 SUPER)
- NVIDIA Container Toolkit installed and configured

Commands:
```bash
cd /path/to/qwen3-vl-1926
docker compose up -d
```

Open the web UI at `http://localhost:5000`.

Services:
- Web UI: `http://localhost:5000` (health: `/health`)
- LLM API: `http://localhost:8000` (health: `/health`)

Notes:
- On first run, the LLM container downloads and initializes the model. This can take several minutes depending on bandwidth and disk.
- The compose file mounts `~/.cache/huggingface` into the LLM container to cache model files.

---

## Usage (Web UI)
1. Pick a mode: Single Pair or Batch.
2. Drag & drop images into the upload area or click to browse.
   - Single Pair: exactly 2 images (page 1 and page 2)
   - Batch: any even number of images; they are paired in sorted order `(0,1), (2,3), ...`
3. Adjust options if needed:
   - Padding (% around ROIs)
   - Generate overlay images
   - Enforce initials validation
4. Click Process.
5. View results in the UI and click Download Results to save the JSON.

Output includes:
- Detected variant (`ua`/`ru`), crop boxes (percent and pixel), normalized FIO, surname+initials band, and nationality with sanity checks.

---

## API (LLM Service)
The LLM service is OpenAI-compatible (served by vLLM):

- Chat completions: `POST /v1/chat/completions`
- Models: `GET /v1/models`
- Health: `GET /health`

Example chat request:
```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
        "model": "Qwen/Qwen3-VL-8B-Instruct-FP8",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 16
      }'
```

---

## Configuration
Environment variables (used by web or pipeline):
- `LLM_ENDPOINT` (default inside containers: `http://llm-service:8000/v1/chat/completions`)
- `LLM_MODEL` (default: `Qwen/Qwen3-VL-8B-Instruct-FP8`)
- `OPENAI_API_KEY` (optional; default `EMPTY`)

Container notes:
- `docker-compose.yml` exposes ports 5000 (web) and 8000 (LLM).
- `~/.cache/huggingface` is mounted into the LLM container for model cache.
- GPU is requested for the LLM container; ensure your runtime honors device requests (Docker Compose v2 or add `gpus: all`).

---

## Development (Local)

You can run the Flask app locally while pointing it to the Dockerized LLM. Recommended steps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

export LLM_ENDPOINT=http://localhost:8000/v1/chat/completions
export LLM_MODEL=Qwen/Qwen3-VL-8B-Instruct-FP8

python app.py  # runs http://127.0.0.1:5000
```

Keep the LLM service running via Docker Compose:
```bash
docker compose up -d llm-service
```

Project layout:
```text
app.py                         # Flask web app
kharkov1926_llm_pipeline_v6.py # LLM-only pipeline library & CLI
templates/index.html           # Web UI
static/style.css               # Styles
static/script.js               # Client-side logic (drag-drop, uploads, results)
Dockerfile.web                 # Web app image
Dockerfile.llm                 # vLLM server image
docker-compose.yml             # Two-service stack (web + llm)
```

---

## Troubleshooting

LLM container shows "unhealthy" but logs look fine:
- Probe race or IPv6 localhost can cause false negatives. Either extend the healthcheck (`start_period`, `retries`) and force IPv4 (`curl --ipv4 http://127.0.0.1:8000/health`), or temporarily disable the healthcheck (current compose disables it).

LLM starts slowly on first run:
- Large model download/initialization. Keep the container running; subsequent starts are faster with cached weights.

No GPU visible in container:
- Ensure NVIDIA Container Toolkit is installed. For Compose v2, device requests are typically honored. Otherwise, add:
```yaml
gpus: all
```

Permission issues with model cache:
- The LLM container mounts `~/.cache/huggingface`. Ensure your host user has read/write permissions.

Out-of-memory or accuracy issues with FP8:
- Consider removing `--kv-cache-dtype fp8` from the LLM command, or lowering `--gpu-memory-utilization`. See `Dockerfile.llm` comments.

---

## License

Specify your license here (e.g., MIT). If unspecified, the project remains All Rights Reserved by default.


