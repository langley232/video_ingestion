import requests
import json
from requests.auth import HTTPDigestAuth

# Atlas API credentials and details
PUBLIC_KEY = "egbjamqo"
PRIVATE_KEY = "c1778243-56de-467d-bedf-78f3559e6dcf"
PROJECT_ID = "Project 0"  # This should be the actual project ID, not the name
CLUSTER_NAME = "test"
DB_NAME = "video_ingestion"
COLLECTION_NAME = "video_frames"
INDEX_NAME = "video_embeddings_index"

# You may need to get the actual project ID from the Atlas UI (not the display name)
# If 'Project 0' does not work, go to Project Settings in Atlas and copy the Project ID (a hex string)

index_def = {
    "name": INDEX_NAME,
    "database": DB_NAME,
    "collection": COLLECTION_NAME,
    "mappings": {
        "dynamic": True,
        "fields": {
            "scene_embedding": {
                "type": "knnVector",
                "dimensions": 1536,
                "similarity": "cosine",
                "quantization": "scalar"
            },
            "detected_objects.object_embedding": {
                "type": "knnVector",
                "dimensions": 768,
                "similarity": "cosine",
                "quantization": "binary"
            },
            "timestamp": {"type": "date"},
            "location": {"type": "geo"},
            "detected_objects.object_type": {"type": "string"}
        }
    }
}

url = f"https://cloud.mongodb.com/api/atlas/v1.0/groups/{PROJECT_ID}/clusters/{CLUSTER_NAME}/fts/indexes"

response = requests.post(
    url,
    auth=HTTPDigestAuth(PUBLIC_KEY, PRIVATE_KEY),
    headers={"Content-Type": "application/json"},
    data=json.dumps(index_def)
)

print("Status:", response.status_code)
try:
    print("Response:", response.json())
except Exception:
    print("Response content:", response.content)
