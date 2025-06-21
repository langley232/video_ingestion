# Video Ingestion & Multimodal Query System

## Overview
This project is a modular, scalable video ingestion and multimodal search system. It supports object detection, scene and object embeddings, vector search, and advanced query refinement using cloud-based LLMs. The system is fully containerized and orchestrated via Docker Compose.

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
- **Port:** 8002 (HTTP), 8003 (gRPC)
- **GPU:** Assignable

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
├── triton_manager.py         # Automates model export and repo setup
├── setup_triton.py           # Fully automates Triton deployment
├── triton_client.py          # Example Triton inference client
├── triton_models/            # Triton model repository (auto-generated)
├── docker-compose.yml        # Orchestration for all services
├── REFACTOR_INSTRUCTIONS.md  # Detailed refactor and architecture plan
└── README.md                 # (This file)
```

---

## **Usage Instructions**

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Automate model export and start Triton:**
   ```bash
   python setup_triton.py
   ```
3. **Start all services:**
   ```bash
   docker-compose up --build -d
   ```
4. **Test inference:**
   ```bash
   python triton_client.py
   ```
5. **Access the UI:**
   - Streamlit: [http://localhost:8501](http://localhost:8501)
   - MinIO: [http://localhost:9001](http://localhost:9001)
   - Redpanda Console: [http://localhost:8080](http://localhost:8080)

---

## **Notes**
- All model inference (YOLO, CLIP) is routed through Triton for scalability and GPU efficiency.
- LLM-based query refinement is handled via Fireworks.ai or Gemini cloud (not local GPU).
- MongoDB Atlas is used for vector search and metadata storage.
- MinIO can be swapped for AWS S3 or MinIO cloud for production.

---

For more details, see `REFACTOR_INSTRUCTIONS.md`. 