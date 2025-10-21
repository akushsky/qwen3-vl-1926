# Kharkov-1926 Docker Setup

This Docker Compose setup runs the Kharkov-1926 document processing pipeline with both the web application and LLM service.

## Prerequisites

1. **Docker and Docker Compose** installed
2. **NVIDIA Docker** (nvidia-docker2) for GPU support
3. **NVIDIA GPU** with CUDA support
4. **Sufficient GPU memory** (recommended 8GB+ VRAM)

## Quick Start

1. **Clone and navigate to the project directory**
   ```bash
   cd /path/to/qwen3-vl-1926
   ```

2. **Start the services**
   ```bash
   docker-compose up -d
   ```

3. **Check service status**
   ```bash
   docker-compose ps
   ```

4. **View logs**
   ```bash
   # View all logs
   docker-compose logs -f
   
   # View specific service logs
   docker-compose logs -f web-app
   docker-compose logs -f llm-service
   ```

## Services

### LLM Service (Port 8000)
- Runs the vLLM server with Qwen3-VL-8B-Instruct-FP8 model
- Configured with your specified parameters
- Health check endpoint: `http://localhost:8000/health`

### Web Application (Port 5000)
- Flask web interface for document processing
- Connects to LLM service for processing
- Health check endpoint: `http://localhost:5000/health`

## Configuration

### Environment Variables
Copy `.env.example` to `.env` and modify as needed:
```bash
cp .env.example .env
```

### GPU Configuration
The LLM service is configured to use GPU with the following settings:
- `gpu-memory-utilization: 0.88`
- `swap-space: 6`
- `max-model-len: 2466`

### Model Download
The model will be automatically downloaded on first run to `~/.cache/huggingface/`.

## Usage

1. **Access the web interface**: http://localhost:5000
2. **Upload documents** for processing
3. **View results** in the web interface

## Troubleshooting

### GPU Issues
If you encounter GPU-related errors:
```bash
# Check NVIDIA Docker installation
docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu22.04 nvidia-smi

# Check if GPU is accessible in container
docker-compose exec llm-service nvidia-smi
```

### Memory Issues
If you run out of GPU memory:
1. Reduce `gpu-memory-utilization` in the Dockerfile.llm
2. Reduce `max-model-len` parameter
3. Ensure sufficient system RAM for swap space

### Service Dependencies
The web app waits for the LLM service to be healthy before starting. If the LLM service fails to start:
```bash
# Check LLM service logs
docker-compose logs llm-service

# Restart LLM service
docker-compose restart llm-service
```

## Stopping Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

## Development

For development, you can mount the source code:
```yaml
# Add to web-app service in docker-compose.yml
volumes:
  - .:/app
```

## Monitoring

- **Service health**: `docker-compose ps`
- **Resource usage**: `docker stats`
- **Logs**: `docker-compose logs -f [service-name]`
