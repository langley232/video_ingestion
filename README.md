# Video Ingestion & Multimodal Query System

## Overview
This project is a modular, scalable video ingestion and multimodal search system. It supports object detection, scene and object embeddings, vector search, and advanced query refinement using cloud-based LLMs. The system is fully containerized and orchestrated via Docker Compose.

---

## Hardware Specifications

This system is optimized for deployment on NVIDIA Jetson platforms. Below are the recommended configurations:

### High-End Configuration
- **Device:** NVIDIA Jetson AGX Orin 64GB
- **Storage:** 1TB+ NVMe SSD for high-speed data access and storage of video files, embeddings, and models.
- **Notes:** Ideal for handling multiple high-resolution video streams, complex multi-modal models, and demanding real-time analytics at the edge.

### Mid-Range Configuration
- **Device:** NVIDIA Jetson Orin NX 16GB
- **Storage:** 512GB+ NVMe SSD.
- **Notes:** A powerful, cost-effective option suitable for projects with fewer concurrent video streams or slightly less complex models. Still offers excellent performance for a wide range of AI tasks.

---

## Services (docker-compose.yml)

### 1. **minio**
- **Purpose:** S3-compatible object storage for raw video files and metadata.
- **Ports:** 9000 (API), 9001 (console)
- **Data:** Mounted at `minio_data:/data`

### 2. **redpanda**
- **Purpose:** Kafka-compatible event streaming platform for inter-service communication.
- **Ports:** 29092 (Kafka), 9644 (admin), 18082/18081 (proxy/schema)
- **Data:** Mounted at `redpanda-data:/var/lib/redpanda/data`

### 3. **redpanda-console**
- **Purpose:** Web UI for Redpanda/Kafka topic management.
- **Port:** 8080

### 4. **ollama_vision**
- **Purpose:** (Optional) Local LLM/vision model server (Qwen2.5-VL) for multimodal query refinement (can be replaced by Fireworks.ai or Gemini cloud).
- **Port:** 11434
- **GPU:** Assignable

### 5. **ollama_embeddings**
- **Purpose:** (Optional) Local embedding model server (Nomic-embed-text) for text/image embeddings.
- **Port:** 11435
- **GPU:** Assignable

### 6. **ingestion**
- **Purpose:** Handles video ingestion, frame extraction, object detection (YOLO via Triton), and embedding (CLIP via Triton). Stores results in MinIO and MongoDB Atlas.
- **Port:** 8000

### 7. **storage**
- **Purpose:** Consumes Kafka events, fetches metadata from MinIO, and writes to MongoDB Atlas. Provides vector search API.
- **Port:** 8001

### 8. **query_alert**
- **Purpose:** Consumes events, applies business logic for alerts, and can interact with LLMs for query refinement.
- **Port:** 8003

### 9. **streamlit_app**
- **Purpose:** User interface for video upload, search, and alert visualization.
- **Port:** 8501

### 10. **audio_backend**
- **Purpose:** Audio processing (e.g., TTS/ASR) via ElevenLabs API.
- **Port:** 8002

### 11. **triton**
- **Purpose:** NVIDIA Triton Inference Server for serving YOLO and CLIP models (and others). All model inference is routed here.
- **Port:** 8004 (HTTP), 8005 (gRPC)
- **GPU:** Assignable

### 12. **triton-model-prep**
- **Purpose:** Automated model preparation service that exports YOLO and CLIP models to ONNX format and sets up the Triton model repository.
- **Dependencies:** Runs before Triton server to prepare models
- **GPU:** Not required (model preparation only)

---

## Directory Structure & Key Files

```
video_ingestion/
├── audio_api/                # Audio backend service
│   └── backend/
│       ├── main.py
│       ├── Dockerfile
│       └── requirements.txt
├── drone_detection_training/ # (Optional) Training scripts and tools
│   ├── fine_tuning/
│   ├── image_collector/
│   ├── model_manager/
│   └── streamlit_app/
├── ingestion/                # Video ingestion service
│   ├── embedding_generator.py   # Embedding via Triton
│   ├── ingestion.py            # Main FastAPI app
│   ├── object_detection/
│   │   ├── detector.py         # YOLO via Triton
│   │   └── __init__.py
│   ├── requirements.txt
│   └── Dockerfile
├── minio/                    # MinIO Docker setup
│   └── Dockerfile
├── ollama/                   # Ollama LLM Docker setup
│   └── entrypoint.sh
├── query_alert/              # Query/alert service
│   ├── query_alert.py
│   ├── requirements.txt
│   └── Dockerfile
├── redpanda/                 # Redpanda/Kafka setup
│   └── data/
├── storage/                  # Storage and vector search service
│   ├── app.py
│   ├── mongodb_client.py      # MongoDB Atlas integration
│   ├── create_vector_index.py # Script for Atlas vector index
│   ├── requirements.txt
│   └── Dockerfile
├── streamlit/                # Streamlit UI
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── triton/                   # Triton infrastructure
│   ├── Dockerfile            # Model preparation service
│   ├── requirements.txt      # Model preparation dependencies
│   └── setup_triton.py       # Model export and repository setup
├── setup_triton_infrastructure.sh # Complete Triton setup script
├── triton_client.py          # External Triton testing client
├── requirements.txt          # Host dependencies for testing
├── triton_models/            # Triton model repository (auto-generated)
├── docker-compose.yml        # Orchestration for all services
├── REFACTOR_INSTRUCTIONS.md  # Detailed refactor and architecture plan
└── README.md                 # (This file)
```

---

## **Usage Instructions**

### **Quick Start (Recommended)**
1. **Install host dependencies for testing:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Start all services (includes automated Triton setup):**
   ```bash
   docker-compose up --build -d
   ```
3. **Test Triton inference:**
   ```bash
   python triton_client.py
   ```

### **Advanced Management**
For additional management features, use the setup script:
```bash
# Make script executable
chmod +x setup_triton_infrastructure.sh

# Setup and start Triton infrastructure
./setup_triton_infrastructure.sh

# Start all services
./setup_triton_infrastructure.sh start-all

# View logs
./setup_triton_infrastructure.sh logs

# Check status
./setup_triton_infrastructure.sh status

# Test inference
./setup_triton_infrastructure.sh test
```

### **Access the UI:**
- Streamlit: [http://localhost:8501](http://localhost:8501)
- MinIO: [http://localhost:9001](http://localhost:9001)
- Redpanda Console: [http://localhost:8080](http://localhost:8080)
- Triton Server: [http://localhost:8004](http://localhost:8004)

---

## **Root-Level Files Explanation**

### **`requirements.txt`**
- **Purpose**: Host dependencies for external testing
- **Contains**: `tritonclient[http]` for testing Triton from host machine
- **Used by**: `triton_client.py` and other host-side tools

### **`triton_client.py`**
- **Purpose**: External testing client for Triton inference
- **Usage**: Test YOLO and CLIP models after services are running
- **Location**: Root directory for easy access from host machine

### **`setup_triton_infrastructure.sh`**
- **Purpose**: Comprehensive Triton management script
- **Features**: Setup, testing, monitoring, and management commands
- **Alternative**: Can use `docker-compose` directly for basic operations

---

## **Triton Infrastructure**

The Triton infrastructure is fully integrated into the main docker-compose.yml:

### **Services:**
- **triton-model-prep**: Automatically exports YOLO and CLIP models to ONNX format
- **triton**: NVIDIA Triton Inference Server serving the prepared models

### **Ports:**
- **8004**: Triton HTTP API (external access)
- **8005**: Triton gRPC API (external access)
- **Internal**: Services use `http://triton:8000` (Docker network)

### **Automated Flow:**
```
1. triton-model-prep starts → exports models to ONNX
2. triton-model-prep completes → models ready in ./triton_models/
3. triton server starts → loads models from ./triton_models/
4. triton becomes healthy → ready for inference
5. Other services start → can call Triton for inference
```

---

## **Notes**
- All model inference (YOLO, CLIP) is routed through Triton for scalability and GPU efficiency.
- The Triton infrastructure is fully dockerized and integrated with the main application.
- Model preparation is automated and runs before the Triton server starts.
- Port conflicts have been resolved by updating Triton ports to 8004/8005.
- LLM-based query refinement is handled via Fireworks.ai or Gemini cloud (not local GPU).
- MongoDB Atlas is used for vector search and metadata storage.
- MinIO can be swapped for AWS S3 or MinIO cloud for production.

---

For more details, see `REFACTOR_INSTRUCTIONS.md`.