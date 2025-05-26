This document outlines the architecture, code flow, and data flow of the video_ingestion application, based on the provided directory structure and a review of the associated code on GitHub.

The video_ingestion application is designed to ingest video data, process it, store it, potentially analyze it with an LLM, and provide a mechanism for querying and alerting, all accessible via a Streamlit-based user interface. The system leverages Docker and Docker Compose for containerization and orchestration, with Kafka for message queuing and MinIO for object storage.

Architecture
The application is composed of several microservices, orchestrated by Docker Compose, each serving a specific function:

Ingestion Service (ingestion): Responsible for receiving video input (though the current ingestion.py seems to be a placeholder or under development for actual video ingestion logic), and likely producing messages to Kafka upon new video events.
Kafka (kafka): Acts as a distributed streaming platform, decoupling producers (like ingestion) from consumers (query_alert, video_gen). It uses ZooKeeper for coordination.
MinIO (minio): An S3-compatible object storage server used for storing raw video files and potentially processed video outputs or metadata.
Ollama (ollama): A service for running large language models (LLMs) locally. It's likely intended for video content analysis, transcription, or generating textual summaries/alerts based on video events.
Query Alert Service (query_alert): Consumes messages from Kafka, processes them to identify specific events or patterns, and potentially triggers alerts or further actions.
Storage Service (storage): A web service (likely Flask, given app.py) that interacts with MinIO for uploading, downloading, or managing stored video data.
Streamlit (streamlit): Provides the user interface (UI) for the application. Users can likely interact with the system to initiate ingestion, view stored videos, trigger queries, or see alerts.
Video Generation Service (video_gen): A service dedicated to video processing or generation tasks, potentially using pre-trained models. It might consume video data or metadata from Kafka, process it, and store results back in MinIO.
Diagram of Architecture:

Code snippet

graph TD
    User -- Interaction --> Streamlit
    Streamlit -- Upload/Trigger --> Ingestion
    Ingestion -- New Video Event --> Kafka
    Kafka -- Video/Event Data --> Query_Alert
    Kafka -- Video/Metadata --> Video_Gen
    Ingestion -- Store Video --> MinIO
    Video_Gen -- Store Processed Video --> MinIO
    Streamlit -- Retrieve/Display --> MinIO
    Query_Alert -- Alerts/Results --> Streamlit
    Video_Gen -- Inference Request --> Ollama
    Ollama -- LLM Output --> Video_Gen
    Streamlit -- Query --> Storage
    Storage -- Access --> MinIO

    subgraph Core Services
        Kafka
        MinIO
        Ollama
    end

    subgraph Application Services
        Ingestion
        Query_Alert
        Video_Gen
        Storage
        Streamlit
    end
Code Flow
Orchestration (docker-compose.yml):

docker-compose up brings up all services.
zookeeper and kafka are started first due to dependencies.
minio is started for object storage.
ollama loads the specified LLM model (llama3).
ingestion, storage, query_alert, video_gen, and streamlit services are then initialized.
kafka/create_topic.sh is executed as part of the Kafka service startup to ensure necessary topics are available.
Kafka Setup (kafka directory):

start.sh (or start.sh.old) typically starts ZooKeeper and Kafka brokers.
create_topic.sh ensures that Kafka topics (e.g., video-events, processed-videos, alerts) are created for inter-service communication.
MinIO Setup (minio directory):

The Dockerfile simply sets up MinIO. MinIO is then accessible for other services (like ingestion, storage, video_gen) to interact with via its S3-compatible API.
Ollama Setup (ollama directory):

entrypoint.sh within the ollama container is responsible for running the ollama serve command and pulling the llama3 model. This makes the LLM available via an API.
Ingestion (ingestion directory):

ingestion.py (current placeholder) would typically:
Receive video data (e.g., via an API endpoint, file upload).
Upload the raw video file to MinIO.
Publish a message to a Kafka topic (e.g., video-events) with metadata about the ingested video (e.g., MinIO path, timestamp).
Storage (storage directory):

app.py (likely a Flask application) provides an API for interacting with MinIO. It would expose endpoints for:
Uploading files to MinIO.
Downloading files from MinIO.
Listing files in MinIO buckets.
The streamlit service would likely call these endpoints to manage files in MinIO.
Video Generation/Processing (video_gen directory):

download_model.py: Fetches any necessary models (e.g., image generation, video processing models) required for inference.py.
inference.py:
Likely acts as a Kafka consumer, listening to video-events or another processing-related topic.
Upon receiving a message, it downloads the video from MinIO.
It performs video processing/generation (e.g., frame extraction, object detection, or creating new video content).
It might send parts of the video (e.g., specific frames, extracted text from ASR) to the ollama service for LLM-based analysis.
It stores the processed video or extracted data back into MinIO.
It may publish a new message to a Kafka topic (e.g., processed-videos) indicating completion.
Query Alert (query_alert directory):

query_alert.py:
Acts as a Kafka consumer, likely subscribing to video-events or processed-videos topics.
It applies business logic or rules to the consumed messages to identify specific conditions (e.g., "drone detected," "person entered zone").
If a condition is met, it could:
Log an alert.
Send a notification (e.g., email, push notification - though not explicitly in the code, this is a typical extension).
Publish a message to another Kafka topic (e.g., alerts) that the Streamlit UI consumes.
Streamlit UI (streamlit directory):

app.py:
Provides the interactive web interface.
Allows users to initiate video ingestion (e.g., by uploading a file, which triggers a call to the ingestion service).
Displays a list of ingested or processed videos (by querying the storage service/MinIO).
Visualizes alerts or processed data received from the query_alert service (potentially by consuming a Kafka topic or calling an API).
Could provide an interface to trigger video_gen processing on demand or configure query_alert rules.
Data Flow
User to Ingestion:

A user uploads a video file via the Streamlit UI.
Streamlit sends the video data to the ingestion service (e.g., via an HTTP POST request).
Ingestion to Storage & Kafka:

The ingestion service receives the video.
It uploads the raw video file to a designated bucket in MinIO.
It then publishes a message (containing metadata like file path in MinIO, timestamp, original filename) to the video-events topic in Kafka.
Kafka to Video Processing:

The video_gen service, acting as a Kafka consumer, subscribes to the video-events topic.
Upon receiving a message, video_gen downloads the raw video from MinIO using the provided path.
video_gen performs its video processing (e.g., frame extraction, feature analysis, video generation).
If LLM analysis is required, relevant data (e.g., extracted frames, transcribed audio text) is sent to the Ollama service for inference.
The processed video or extracted data is stored back into MinIO.
video_gen may publish a message to a processed-videos topic in Kafka to signify completion and availability of processed data.
Kafka to Query/Alerting:

The query_alert service, acting as a Kafka consumer, subscribes to video-events and/or processed-videos topics.
It analyzes the message content based on defined rules.
If an alert condition is met, it generates an alert. This alert could be logged, sent to an external notification system, or published to an alerts topic in Kafka.
Storage and Retrieval for UI:

The Streamlit UI retrieves lists of videos or specific video files from MinIO (via the storage service) to display to the user.
The Streamlit UI consumes messages from the alerts topic (if implemented this way) or polls the query_alert service to display real-time alerts.
Ollama Interaction:

The video_gen service sends requests to the ollama service's API for LLM inference (e.g., asking "What objects are in this image?", "Summarize this text").
ollama processes the request using the loaded llama3 model and returns the LLM's output back to video_gen.
Summary of Data Movement:

Video Files: User Upload
rightarrow Streamlit
rightarrow Ingestion Service
leftrightarrow MinIO
leftrightarrow Video Generation Service.
Metadata/Events: Ingestion Service
rightarrow Kafka
rightarrow Video Generation Service / Query Alert Service.
Processed Data: Video Generation Service
rightarrow MinIO; Video Generation Service
rightarrow Kafka.
Alerts: Query Alert Service
rightarrow (Kafka)
rightarrow Streamlit UI.
LLM Inference Data: Video Generation Service
leftrightarrow Ollama Service.
