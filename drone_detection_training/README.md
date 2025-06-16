# Drone Detection Training Service

This service helps you collect drone images, fine-tune the Moondream model, and deploy it to Ollama for improved drone detection.

## Components

1. **Image Collection Service**
   - Collects drone images using SerpAPI
   - Stores images and metadata in MinIO
   - Supports both single query and full dataset collection

2. **Fine-tuning Service**
   - Prepares datasets from collected images
   - Fine-tunes the Moondream model
   - Saves trained models to MinIO

3. **Model Manager Service**
   - Manages trained models
   - Deploys models to Ollama
   - Provides model versioning

4. **Streamlit UI**
   - User-friendly interface for all services
   - Real-time feedback on operations
   - Easy configuration of parameters

## Prerequisites

- Docker and Docker Compose
- SerpAPI key for image collection
- Sufficient disk space for images and models

## Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd drone_detection_training
```

2. Set up environment variables:
```bash
export SERPAPI_API_KEY=your_api_key_here
```

3. Start the services:
```bash
docker-compose up --build
```

4. Access the services:
   - Streamlit UI: http://localhost:8501
   - MinIO Console: http://localhost:9001
   - Image Collector API: http://localhost:8001
   - Fine-tuning API: http://localhost:8002
   - Model Manager API: http://localhost:8003

## Usage

1. **Image Collection**
   - Use the "Image Collection" tab in the Streamlit UI
   - Choose between single query or full dataset collection
   - Configure search parameters and categories

2. **Model Training**
   - Use the "Model Training" tab
   - Configure training parameters
   - Prepare dataset and train model
   - Monitor training progress

3. **Model Deployment**
   - Use the "Model Deployment" tab
   - Select a trained model
   - Deploy to Ollama
   - Verify deployment status

## Directory Structure

```
drone_detection_training/
├── docker-compose.yml
├── README.md
├── image_collector/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py
│   └── serp_api_client.py
├── fine_tuning/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py
│   └── training/
│       ├── dataset.py
│       ├── model.py
│       └── trainer.py
├── model_manager/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
└── streamlit_app/
    ├── Dockerfile
    ├── requirements.txt
    └── app.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 