# Video Ingestion System Refactor Instructions

## Overview
This document outlines the comprehensive refactoring plan to transform the current video ingestion system into a production-ready, scalable platform with advanced object detection, multi-modal embeddings, and intelligent query capabilities.

## Current System Analysis

### ✅ Existing Components
- **MinIO**: Object storage for videos and metadata
- **RedPanda (Kafka)**: Message queuing and event streaming
- **Ollama Services**: 
  - Qwen2.5-VL (vision model) for basic object detection
  - Nomic-embed-text for embeddings
- **FAISS**: Vector similarity search (CPU-based)
- **Basic Pipeline**: Video ingestion → Kafka → Storage → Query Alert

### 🔄 Areas for Enhancement
- **Object Detection**: Currently basic drone detection, needs comprehensive object detection
- **Embeddings**: Limited to single frame embeddings, needs multi-modal approach
- **Vector Database**: FAISS is in-memory, needs production-ready solution
- **Query System**: Basic similarity search, needs advanced query capabilities

## Phase 1: Enhanced Ingestion Pipeline (Offline/Batch)

### 1.1 Object Detection Enhancement

#### Current State
```python
# query_alert/query_alert.py - Basic drone detection
DETECTION_CONFIG = {
    "target_objects": ["drone", "military drone", "UAV", ...],
    "confidence_threshold": 0.3,
    "model": "qwen2.5vl:3b"
}
```

#### Target Implementation
```python
# Enhanced object detection with YOLO/Grounding DINO
class ObjectDetector:
    def __init__(self):
        self.yolo_model = YOLO('yolov8x.pt')  # or Grounding DINO
        self.clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    
    def detect_objects(self, frame):
        # YOLO detection
        results = self.yolo_model(frame)
        
        # Extract bounding boxes, classes, confidence scores
        detections = []
        for result in results:
            boxes = result.boxes
            for box in boxes:
                detection = {
                    "object_type": self.yolo_model.names[int(box.cls)],
                    "confidence": float(box.conf),
                    "bounding_box": box.xyxy[0].tolist(),
                    "object_embedding": self.generate_object_embedding(frame, box)
                }
                detections.append(detection)
        
        return detections
```

#### Implementation Steps
1. **Add Dependencies** to `ingestion/requirements.txt`:
   ```
   ultralytics>=8.0.0  # YOLO
   transformers>=4.30.0  # CLIP/SigLIP
   torch>=2.0.0
   torchvision>=0.15.0
   ```

2. **Create Object Detection Service**:
   ```bash
   mkdir -p object_detection
   touch object_detection/{__init__.py,detector.py,models.py}
   ```

3. **Integrate with Ingestion Pipeline**:
   - Modify `ingestion/ingestion.py` to use enhanced detector
   - Add frame extraction and processing
   - Generate object embeddings for each detection

### 1.2 Multi-Modal Embedding Generation

#### Scene Embeddings (CLIP/SigLIP)
```python
class SceneEmbeddingGenerator:
    def __init__(self):
        self.clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        self.clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    
    def generate_scene_embedding(self, frame):
        # Process frame for CLIP
        inputs = self.clip_processor(images=frame, return_tensors="pt")
        
        # Generate embedding
        with torch.no_grad():
            image_features = self.clip_model.get_image_features(**inputs)
        
        return image_features.cpu().numpy().flatten()
```

#### Object Embeddings
```python
class ObjectEmbeddingGenerator:
    def generate_object_embedding(self, frame, bounding_box):
        # Crop object from frame
        x1, y1, x2, y2 = bounding_box
        object_crop = frame[int(y1):int(y2), int(x1):int(x2)]
        
        # Generate embedding for cropped object
        inputs = self.clip_processor(images=object_crop, return_tensors="pt")
        with torch.no_grad():
            object_features = self.clip_model.get_image_features(**inputs)
        
        return object_features.cpu().numpy().flatten()
```

### 1.3 Enhanced Data Structure

#### Current Metadata Structure
```json
{
  "ingestion_id": "uuid",
  "original_filename": "video.mp4",
  "timestamp": "2024-01-01T10:00:00Z",
  "location": {"latitude": 40.7829, "longitude": -73.9654},
  "video_metadata": {"width": 1920, "height": 1080, "fps": 30}
}
```

#### Target Enhanced Structure
```json
{
  "video_id": "uuid",
  "ingestion_metadata": {
    "original_filename": "video.mp4",
    "ingestion_time": "2024-01-01T10:00:00Z",
    "location": {"latitude": 40.7829, "longitude": -73.9654, "name": "Central Park"},
    "video_metadata": {"width": 1920, "height": 1080, "fps": 30, "duration": 120}
  },
  "frames": [
    {
      "frame_id": "uuid",
      "timestamp": "2024-01-01T10:00:05Z",
      "frame_number": 150,
      "scene_embedding": [0.1, 0.2, ...],
      "objects": [
        {
          "object_id": "uuid",
          "object_type": "car",
          "confidence": 0.95,
          "bounding_box": [100, 200, 300, 400],
          "object_embedding": [0.3, 0.4, ...],
          "attributes": {
            "color": "red",
            "size": "medium",
            "orientation": "north"
          }
        }
      ]
    }
  ]
}
```

## Phase 2: MongoDB Atlas Integration

### 2.1 Replace FAISS with MongoDB Atlas

#### Current FAISS Implementation
```python
# storage/app.py
faiss_index = faiss.IndexFlatL2(dimension)
faiss_id_to_metadata_map = []  # In-memory mapping
```

#### MongoDB Atlas Implementation
```python
# New: storage/mongodb_client.py
from pymongo import MongoClient
from pymongo.server_api import ServerApi

class MongoDBAtlasClient:
    def __init__(self):
        self.client = MongoClient(
            os.getenv("MONGODB_URI"),
            server_api=ServerApi('1')
        )
        self.db = self.client.video_ingestion
        self.frames_collection = self.db.frames
        
        # Create vector search index
        self.create_vector_index()
    
    def create_vector_index(self):
        index_definition = {
            "mappings": {
                "dynamic": True,
                "fields": {
                    "scene_embedding": {
                        "dimensions": 512,
                        "similarity": "cosine",
                        "type": "knnVector"
                    },
                    "objects.object_embedding": {
                        "dimensions": 512,
                        "similarity": "cosine",
                        "type": "knnVector"
                    }
                }
            }
        }
        
        self.frames_collection.create_search_index(index_definition)
    
    def insert_frame(self, frame_data):
        return self.frames_collection.insert_one(frame_data)
    
    def vector_search(self, query_embedding, filter_criteria=None):
        pipeline = [
            {
                "$search": {
                    "index": "default",
                    "knnBeta": {
                        "vector": query_embedding,
                        "path": "scene_embedding",
                        "k": 10
                    }
                }
            }
        ]
        
        if filter_criteria:
            pipeline.append({"$match": filter_criteria})
        
        return list(self.frames_collection.aggregate(pipeline))
```

### 2.2 Update Storage Service

#### Modify `storage/app.py`:
```python
# Replace FAISS imports with MongoDB
from storage.mongodb_client import MongoDBAtlasClient

# Initialize MongoDB client
mongodb_client = MongoDBAtlasClient()

# Update search endpoint
@app.post("/search")
async def search_videos(query_embedding: list, filters: dict = None):
    try:
        results = mongodb_client.vector_search(query_embedding, filters)
        return {"similar_videos": results}
    except Exception as e:
        logger.error(f"Error searching videos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
```

### 2.3 Environment Configuration

#### Add to `docker-compose.yml`:
```yaml
services:
  storage:
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - MONGODB_DATABASE=video_ingestion
```

#### Add to `.env`:
```env
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/video_ingestion?retryWrites=true&w=majority
```

## Phase 3: Advanced Query System

### 3.1 Query Processing Pipeline

#### Query Parser
```python
# New: query_processor/parser.py
import re
from datetime import datetime
from typing import Dict, List, Any

class QueryParser:
    def __init__(self):
        self.temporal_patterns = [
            r"between\s+(\d{1,2}:\d{2})\s+and\s+(\d{1,2}:\d{2})",
            r"at\s+(\d{1,2}:\d{2})",
            r"(\d{1,2}:\d{2})\s+to\s+(\d{1,2}:\d{2})"
        ]
        
        self.spatial_patterns = [
            r"in\s+([A-Za-z\s]+)",
            r"near\s+([A-Za-z\s]+)",
            r"at\s+([A-Za-z\s]+)"
        ]
    
    def parse_query(self, query: str) -> Dict[str, Any]:
        parsed = {
            "objects": [],
            "attributes": {},
            "temporal": {},
            "spatial": {},
            "raw_query": query
        }
        
        # Extract object types
        parsed["objects"] = self.extract_objects(query)
        
        # Extract attributes
        parsed["attributes"] = self.extract_attributes(query)
        
        # Extract temporal constraints
        parsed["temporal"] = self.extract_temporal(query)
        
        # Extract spatial constraints
        parsed["spatial"] = self.extract_spatial(query)
        
        return parsed
    
    def extract_objects(self, query: str) -> List[str]:
        # Use NER or keyword extraction
        object_keywords = ["car", "person", "drone", "bicycle", "truck"]
        found_objects = []
        
        for obj in object_keywords:
            if obj in query.lower():
                found_objects.append(obj)
        
        return found_objects
    
    def extract_attributes(self, query: str) -> Dict[str, str]:
        attributes = {}
        
        # Color extraction
        color_pattern = r"(red|blue|green|yellow|black|white|gray|grey)\s+(\w+)"
        color_matches = re.findall(color_pattern, query.lower())
        for color, obj in color_matches:
            attributes[f"{obj}_color"] = color
        
        return attributes
    
    def extract_temporal(self, query: str) -> Dict[str, str]:
        temporal = {}
        
        for pattern in self.temporal_patterns:
            matches = re.findall(pattern, query.lower())
            if matches:
                if len(matches[0]) == 2:  # between pattern
                    temporal["start_time"] = matches[0][0]
                    temporal["end_time"] = matches[0][1]
                else:  # at pattern
                    temporal["exact_time"] = matches[0]
                break
        
        return temporal
    
    def extract_spatial(self, query: str) -> Dict[str, str]:
        spatial = {}
        
        for pattern in self.spatial_patterns:
            matches = re.findall(pattern, query.lower())
            if matches:
                spatial["location"] = matches[0].strip()
                break
        
        return spatial
```

### 3.2 Multimodal LLM Integration

#### Query Refinement with Qwen2.5-VL
```python
# New: query_processor/llm_refiner.py
class QueryRefiner:
    def __init__(self, ollama_endpoint: str):
        self.ollama_endpoint = ollama_endpoint
    
    def refine_query(self, query: str, context: str = None) -> Dict[str, Any]:
        prompt = f"""
        Analyze this video query and extract structured information:
        Query: "{query}"
        Context: {context or "No additional context"}
        
        Return a JSON object with:
        - objects: list of object types to search for
        - attributes: object attributes (color, size, etc.)
        - temporal: time constraints
        - spatial: location constraints
        - confidence: confidence in each extraction
        """
        
        response = requests.post(
            f"{self.ollama_endpoint}/api/generate",
            json={
                "model": "qwen2.5vl:3b",
                "prompt": prompt,
                "format": "json",
                "stream": False
            }
        )
        
        return response.json()
    
    def generate_query_embedding(self, refined_query: Dict[str, Any]) -> List[float]:
        # Convert refined query to text for embedding
        query_text = self.query_to_text(refined_query)
        
        response = requests.post(
            f"{self.ollama_endpoint}/api/embeddings",
            json={
                "model": "nomic-embed-text:latest",
                "prompt": query_text
            }
        )
        
        return response.json()["embedding"]
    
    def query_to_text(self, refined_query: Dict[str, Any]) -> str:
        parts = []
        
        if refined_query.get("objects"):
            parts.append(f"objects: {', '.join(refined_query['objects'])}")
        
        if refined_query.get("attributes"):
            for key, value in refined_query["attributes"].items():
                parts.append(f"{key}: {value}")
        
        if refined_query.get("temporal"):
            parts.append(f"time: {refined_query['temporal']}")
        
        if refined_query.get("spatial"):
            parts.append(f"location: {refined_query['spatial']}")
        
        return " ".join(parts)
```

### 3.3 Advanced Search Implementation

#### Enhanced Search Service
```python
# New: search_service/search_engine.py
class VideoSearchEngine:
    def __init__(self, mongodb_client, query_parser, query_refiner):
        self.mongodb_client = mongodb_client
        self.query_parser = query_parser
        self.query_refiner = query_refiner
    
    async def search(self, query: str, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        # Parse natural language query
        parsed_query = self.query_parser.parse_query(query)
        
        # Refine with LLM
        refined_query = self.query_refiner.refine_query(query)        
        # Generate query embedding
        query_embedding = self.query_refiner.generate_query_embedding(refined_query)
        
        # Build MongoDB filter
        mongo_filter = self.build_mongo_filter(parsed_query, refined_query, filters)
        
        # Perform vector search
        results = self.mongodb_client.vector_search(query_embedding, mongo_filter)
        
        # Post-process results
        processed_results = self.post_process_results(results, parsed_query)
        
        return processed_results
    
    def build_mongo_filter(self, parsed_query: Dict, refined_query: Dict, additional_filters: Dict = None) -> Dict:
        filter_conditions = {}
        
        # Object type filter
        if refined_query.get("objects"):
            filter_conditions["objects.object_type"] = {"$in": refined_query["objects"]}
        
        # Temporal filter
        if refined_query.get("temporal"):
            temporal_filter = self.build_temporal_filter(refined_query["temporal"])
            if temporal_filter:
                filter_conditions.update(temporal_filter)
        
        # Spatial filter
        if refined_query.get("spatial"):
            spatial_filter = self.build_spatial_filter(refined_query["spatial"])
            if spatial_filter:
                filter_conditions.update(spatial_filter)
        
        # Merge with additional filters
        if additional_filters:
            filter_conditions.update(additional_filters)
        
        return filter_conditions if filter_conditions else None
    
    def build_temporal_filter(self, temporal: Dict[str, str]) -> Dict[str, Any]:
        # Convert time constraints to MongoDB date filters
        # Implementation depends on how timestamps are stored
        pass
    
    def build_spatial_filter(self, spatial: Dict[str, str]) -> Dict[str, Any]:
        # Convert location constraints to geospatial filters
        # Implementation depends on location data structure
        pass
    
    def post_process_results(self, results: List[Dict], original_query: Dict) -> List[Dict]:
        # Rank results based on relevance
        # Filter based on additional criteria
        # Format response
        return results
```

## Phase 4: Service Architecture Refactoring

### 4.1 New Service Structure

```
video_ingestion/
├── ingestion/                 # Enhanced video ingestion
│   ├── object_detection/     # YOLO/Grounding DINO integration
│   ├── embedding_generator/  # CLIP/SigLIP embeddings
│   └── frame_processor/      # Frame extraction and processing
├── storage/                  # MongoDB Atlas integration
│   ├── mongodb_client.py    # MongoDB operations
│   └── vector_search.py     # Vector search implementation
├── query_processor/          # Query parsing and refinement
│   ├── parser.py            # Natural language parsing
│   ├── llm_refiner.py       # LLM-based query refinement
│   └── query_builder.py     # MongoDB query construction
├── search_service/           # Advanced search capabilities
│   ├── search_engine.py     # Main search logic
│   └── result_processor.py  # Result ranking and filtering
└── api_gateway/             # Centralized API management
    ├── routes/              # API endpoints
    └── middleware/          # Authentication, rate limiting
```

### 4.2 Updated Docker Compose

```yaml
# docker-compose.yml additions
services:
  # Enhanced ingestion with object detection
  ingestion:
    build:
      context: ./ingestion
      dockerfile: Dockerfile
    environment:
      - YOLO_MODEL_PATH=/app/models/yolov8x.pt
      - CLIP_MODEL_NAME=openai/clip-vit-base-patch32
    volumes:
      - model_cache:/app/models
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  # MongoDB Atlas connection
  storage:
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - MONGODB_DATABASE=video_ingestion
      - VECTOR_INDEX_NAME=video_vectors

  # New query processing service
  query_processor:
    build:
      context: ./query_processor
      dockerfile: Dockerfile
    environment:
      - OLLAMA_VISION_ENDPOINT=http://ollama_vision:11434
      - OLLAMA_EMBEDDINGS_ENDPOINT=http://ollama_embeddings:11434
    ports:
      - "8004:8004"

  # New search service
  search_service:
    build:
      context: ./search_service
      dockerfile: Dockerfile
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - QUERY_PROCESSOR_ENDPOINT=http://query_processor:8004
    ports:
      - "8005:8005"

volumes:
  model_cache:
```

## Phase 5: Performance Optimization

### 5.1 Batch Processing
```python
# ingestion/batch_processor.py
class BatchProcessor:
    def __init__(self, batch_size: int = 32):
        self.batch_size = batch_size
        self.object_detector = ObjectDetector()
        self.embedding_generator = EmbeddingGenerator()
    
    async def process_video_batch(self, video_paths: List[str]):
        # Process multiple videos in parallel
        tasks = [self.process_single_video(path) for path in video_paths]
        return await asyncio.gather(*tasks)
    
    async def process_single_video(self, video_path: str):
        # Extract frames
        frames = self.extract_frames(video_path)
        
        # Process frames in batches
        frame_batches = [frames[i:i+self.batch_size] 
                        for i in range(0, len(frames), self.batch_size)]
        
        results = []
        for batch in frame_batches:
            batch_results = await self.process_frame_batch(batch)
            results.extend(batch_results)
        
        return results
```

### 5.2 Caching Strategy
```python
# cache/redis_client.py
import redis
import json

class CacheManager:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True
        )
    
    def cache_query_result(self, query_hash: str, results: List[Dict], ttl: int = 3600):
        self.redis_client.setex(
            f"query:{query_hash}",
            ttl,
            json.dumps(results)
        )
    
    def get_cached_result(self, query_hash: str) -> Optional[List[Dict]]:
        cached = self.redis_client.get(f"query:{query_hash}")
        return json.loads(cached) if cached else None
```

## Implementation Timeline

### Week 1-2: Enhanced Ingestion
- [ ] Implement YOLO/Grounding DINO object detection
- [ ] Add CLIP/SigLIP embedding generation
- [ ] Update data structures and metadata
- [ ] Test with sample videos

### Week 3-4: MongoDB Atlas Integration
- [ ] Set up MongoDB Atlas cluster
- [ ] Create vector search indexes
- [ ] Migrate from FAISS to MongoDB Atlas
- [ ] Update storage service

### Week 5-6: Query Processing
- [ ] Implement query parser
- [ ] Add LLM-based query refinement
- [ ] Create advanced search engine
- [ ] Test complex queries

### Week 7-8: Service Integration
- [ ] Refactor service architecture
- [ ] Add API gateway
- [ ] Implement caching
- [ ] Performance testing

### Week 9-10: Production Readiness
- [ ] Error handling and monitoring
- [ ] Documentation
- [ ] Deployment automation
- [ ] Load testing

## Dependencies to Add

### ingestion/requirements.txt
```
ultralytics>=8.0.0
transformers>=4.30.0
torch>=2.0.0
torchvision>=0.15.0
opencv-python>=4.8.0
numpy>=1.24.0
pillow>=10.0.0
```

### storage/requirements.txt
```
pymongo>=4.5.0
pymongo[srv]>=4.5.0
redis>=4.6.0
```

### query_processor/requirements.txt
```
fastapi>=0.104.0
uvicorn>=0.24.0
requests>=2.31.0
python-dateutil>=2.8.2
```

## Environment Variables

### .env
```env
# MongoDB Atlas
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/video_ingestion?retryWrites=true&w=majority
MONGODB_DATABASE=video_ingestion

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Model Paths
YOLO_MODEL_PATH=/app/models/yolov8x.pt
CLIP_MODEL_NAME=openai/clip-vit-base-patch32

# Service Endpoints
QUERY_PROCESSOR_ENDPOINT=http://query_processor:8004
SEARCH_SERVICE_ENDPOINT=http://search_service:8005
```

## Testing Strategy

### Unit Tests
- Object detection accuracy
- Embedding generation consistency
- Query parsing accuracy
- Vector search performance

### Integration Tests
- End-to-end video processing
- Query processing pipeline
- MongoDB Atlas operations
- Service communication

### Performance Tests
- Large video processing
- Concurrent query handling
- Vector search scalability
- Memory usage optimization

## Monitoring and Observability

### Metrics to Track
- Video processing time
- Object detection accuracy
- Query response time
- Vector search performance
- Error rates

### Logging Strategy
- Structured logging with correlation IDs
- Performance metrics
- Error tracking
- Query analytics

## Future Enhancements

### Phase 6: Advanced Features
- Real-time video streaming
- Multi-language query support
- Advanced analytics dashboard
- Machine learning model training pipeline

### Phase 7: Scale and Optimization
- Kubernetes deployment
- Auto-scaling
- Multi-region deployment
- Advanced caching strategies

---

## Notes for Implementation

1. **Start Small**: Begin with enhanced object detection in the ingestion service
2. **Test Incrementally**: Test each component before integrating
3. **Monitor Performance**: Track metrics from the beginning
4. **Document Changes**: Update documentation as you implement
5. **Backup Data**: Ensure data safety during migration from FAISS to MongoDB Atlas

This refactor will transform the system into a production-ready, scalable platform capable of handling complex video queries with high accuracy and performance. 
--------------------------------------------------------------------------------
RAW Plan:
-------------------------------------------------------------------------------
