#!/bin/bash

# Complete Triton Infrastructure Setup Script
# This script sets up the Triton infrastructure integrated with the main docker-compose.yml

set -e  # Exit on any error

echo "🚀 Starting Complete Triton Infrastructure Setup..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
check_docker() {
    print_status "Checking Docker installation..."
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    print_success "Docker is running"
}

# Check if NVIDIA Docker runtime is available
check_nvidia_docker() {
    print_status "Checking NVIDIA Docker runtime..."
    if ! docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi > /dev/null 2>&1; then
        print_warning "NVIDIA Docker runtime not available. Triton will run on CPU only."
        print_warning "For optimal performance on Jetson AGX Orin, install NVIDIA Docker runtime."
    else
        print_success "NVIDIA Docker runtime is available"
    fi
}

# Create necessary directories
setup_directories() {
    print_status "Setting up directories..."
    mkdir -p triton_models
    print_success "Directories created"
}

# Copy setup files to triton directory
copy_setup_files() {
    print_status "Copying setup files to triton directory..."
    if [ ! -d "triton" ]; then
        mkdir -p triton
    fi
    
    # Copy setup files if they exist in root
    if [ -f "setup_triton.py" ]; then
        cp setup_triton.py triton/
    fi
    if [ -f "triton_manager.py" ]; then
        cp triton_manager.py triton/
    fi
    
    print_success "Setup files copied"
}

# Build and run Triton infrastructure
deploy_triton() {
    print_status "Building Triton model preparation service..."
    docker-compose build triton-model-prep
    
    print_status "Starting Triton infrastructure..."
    docker-compose up -d triton-model-prep triton
    
    print_status "Waiting for model preparation to complete..."
    # Wait for model prep to finish
    timeout=300  # 5 minutes timeout
    counter=0
    while [ $counter -lt $timeout ]; do
        if ! docker-compose ps triton-model-prep | grep -q "Up"; then
            # Check if the container completed successfully
            if docker-compose ps triton-model-prep | grep -q "Exit 0"; then
                print_success "Model preparation completed successfully!"
                break
            else
                print_error "Model preparation failed!"
                docker-compose logs triton-model-prep
                exit 1
            fi
        fi
        sleep 5
        counter=$((counter + 5))
        echo -n "."
    done
    
    if [ $counter -ge $timeout ]; then
        print_error "Model preparation timed out after $timeout seconds"
        docker-compose logs triton-model-prep
        exit 1
    fi
    
    print_status "Waiting for Triton server to be ready..."
    # Wait for Triton server to be healthy
    timeout=120
    counter=0
    while [ $counter -lt $timeout ]; do
        if curl -f http://localhost:8004/v2/health/ready > /dev/null 2>&1; then
            print_success "Triton server is ready!"
            break
        fi
        sleep 2
        counter=$((counter + 2))
        echo -n "."
    done
    
    if [ $counter -ge $timeout ]; then
        print_error "Triton server failed to start within $timeout seconds"
        docker-compose logs triton
        exit 1
    fi
}

# Test Triton inference
test_inference() {
    print_status "Testing Triton inference..."
    
    # Create a simple test script
    cat > test_triton.py << 'EOF'
import numpy as np
import tritonclient.http as httpclient
import sys

def test_inference():
    try:
        client = httpclient.InferenceServerClient(url="localhost:8004")
        
        # Test YOLO
        yolo_input = np.random.rand(1, 3, 640, 640).astype(np.float32)
        inputs = [httpclient.InferInput("images", yolo_input.shape, "FP32")]
        inputs[0].set_data_from_numpy(yolo_input)
        outputs = [httpclient.InferRequestedOutput("output0")]
        results = client.infer("yolo", inputs, outputs=outputs)
        print("✅ YOLO inference test passed")
        
        # Test CLIP
        clip_input = np.random.rand(1, 3, 224, 224).astype(np.float32)
        inputs = [httpclient.InferInput("input", clip_input.shape, "FP32")]
        inputs[0].set_data_from_numpy(clip_input)
        outputs = [httpclient.InferRequestedOutput("embeddings")]
        results = client.infer("clip", inputs, outputs=outputs)
        print("✅ CLIP inference test passed")
        
        return True
    except Exception as e:
        print(f"❌ Inference test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_inference()
    sys.exit(0 if success else 1)
EOF

    # Install tritonclient if not available
    pip install tritonclient[http] > /dev/null 2>&1 || true
    
    # Run test
    if python test_triton.py; then
        print_success "Triton inference test passed"
        rm test_triton.py
    else
        print_error "Triton inference test failed"
        rm test_triton.py
        exit 1
    fi
}

# Show status
show_status() {
    print_status "Triton Infrastructure Status:"
    echo "----------------------------------------"
    docker-compose ps triton-model-prep triton
    echo ""
    print_status "Available endpoints:"
    echo "  - Triton HTTP: http://localhost:8004"
    echo "  - Triton gRPC: localhost:8005"
    echo "  - Health check: http://localhost:8004/v2/health/ready"
    echo ""
    print_status "Models loaded:"
    curl -s http://localhost:8004/v2/models | python -m json.tool 2>/dev/null || echo "Models endpoint not available yet"
}

# Start all services
start_all_services() {
    print_status "Starting all services..."
    docker-compose up -d
    print_success "All services started"
}

# Main execution
main() {
    echo "=========================================="
    echo "    Complete Triton Infrastructure Setup"
    echo "=========================================="
    echo ""
    
    check_docker
    check_nvidia_docker
    setup_directories
    copy_setup_files
    deploy_triton
    test_inference
    show_status
    
    echo ""
    print_success "🎉 Triton infrastructure setup completed successfully!"
    echo ""
    echo "Next steps:"
    echo "1. Start all services: ./setup_triton_infrastructure.sh start-all"
    echo "2. Access Triton at: http://localhost:8004"
    echo "3. Monitor logs: docker-compose logs -f triton"
    echo "4. Test inference: python triton_client.py"
    echo ""
}

# Handle script arguments
case "${1:-}" in
    "stop")
        print_status "Stopping Triton infrastructure..."
        docker-compose stop triton-model-prep triton
        print_success "Triton infrastructure stopped"
        ;;
    "restart")
        print_status "Restarting Triton infrastructure..."
        docker-compose restart triton-model-prep triton
        print_success "Triton infrastructure restarted"
        ;;
    "start-all")
        print_status "Starting all services..."
        docker-compose up -d
        print_success "All services started"
        ;;
    "logs")
        docker-compose logs -f triton-model-prep triton
        ;;
    "status")
        show_status
        ;;
    "test")
        test_inference
        ;;
    "clean")
        print_status "Cleaning up Triton infrastructure..."
        docker-compose down triton-model-prep triton
        docker system prune -f
        print_success "Triton infrastructure cleaned up"
        ;;
    "help"|"-h"|"--help")
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  (no args)  - Setup and start Triton infrastructure"
        echo "  stop       - Stop Triton infrastructure"
        echo "  restart    - Restart Triton infrastructure"
        echo "  start-all  - Start all services"
        echo "  logs       - Show Triton logs"
        echo "  status     - Show Triton status"
        echo "  test       - Test Triton inference"
        echo "  clean      - Clean up Triton infrastructure"
        echo "  help       - Show this help message"
        ;;
    *)
        main
        ;;
esac 