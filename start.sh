#!/bin/bash

# Kharkov-1926 Docker Startup Script

echo "🚀 Starting Kharkov-1926 Document Processing Pipeline..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if nvidia-docker is available
if ! docker run --rm --gpus all nvidia/cuda:12.1.1-runtime-ubuntu22.04 nvidia-smi > /dev/null 2>&1; then
    echo "⚠️  Warning: NVIDIA Docker not detected. GPU acceleration may not work."
    echo "   Make sure nvidia-docker2 is installed and Docker is configured for GPU support."
fi

# Create necessary directories
echo "📁 Creating necessary directories..."
mkdir -p uploads results

# Start services
echo "🐳 Starting Docker Compose services..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check service status
echo "📊 Checking service status..."
docker-compose ps

# Check health endpoints
echo "🏥 Checking service health..."

# Check LLM service
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ LLM service is healthy"
else
    echo "❌ LLM service is not responding"
    echo "   Check logs with: docker-compose logs llm-service"
fi

# Check web app
if curl -f http://localhost:5000/health > /dev/null 2>&1; then
    echo "✅ Web application is healthy"
    echo ""
    echo "🎉 Services are ready!"
    echo "   Web interface: http://localhost:5000"
    echo "   LLM API: http://localhost:8000"
else
    echo "❌ Web application is not responding"
    echo "   Check logs with: docker-compose logs web-app"
fi

echo ""
echo "📝 Useful commands:"
echo "   View logs: docker-compose logs -f"
echo "   Stop services: docker-compose down"
echo "   Restart: docker-compose restart"
echo "   Status: docker-compose ps"
