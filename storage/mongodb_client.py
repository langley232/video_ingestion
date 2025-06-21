import os
import logging
from pymongo import MongoClient, ASCENDING
from pymongo.errors import CollectionInvalid
from pymongo.server_api import ServerApi
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class MongoDBAtlasClient:
    def __init__(self):
        self.uri = os.getenv("MONGODB_URI")
        self.db_name = os.getenv("MONGODB_DATABASE", "video_ingestion")
        self.collection_name = os.getenv("MONGODB_COLLECTION", "video_frames")
        self.vector_index_name = os.getenv(
            "MONGODB_VECTOR_INDEX", "video_embeddings_index")
        self.client = MongoClient(self.uri, server_api=ServerApi('1'))
        self.db = self.client[self.db_name]
        self.collection = self.db[self.collection_name]
        self.ensure_collection_and_indexes()

    def ensure_collection_and_indexes(self):
        # Ensure collection exists by inserting a dummy doc if empty
        if self.collection.estimated_document_count() == 0:
            logger.info(
                f"Collection {self.collection_name} is empty. Inserting dummy doc to ensure creation.")
            self.collection.insert_one({"_init": True})
            self.collection.delete_many({"_init": True})
        # Ensure regular indexes
        logger.info("Ensuring regular indexes...")
        self.collection.create_index([("timestamp", ASCENDING)])
        self.collection.create_index([("location", "2dsphere")])
        self.collection.create_index(
            [("detected_objects.object_type", ASCENDING)])
        logger.info("Regular indexes ensured.")
        # Check for Atlas Vector Search index (cannot create via PyMongo)
        self.print_vector_index_instructions()

    def print_vector_index_instructions(self):
        logger.warning(
            "PyMongo cannot create Atlas Vector Search indexes. Please ensure the following index exists in Atlas UI:")
        print("""
Go to Atlas UI → Search → Create Search Index → JSON Editor, and use:
{
  "mappings": {
    "dynamic": true,
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
      "timestamp": { "type": "date" },
      "location": { "type": "geo" },
      "detected_objects.object_type": { "type": "string" }
    }
  }
}
        """)

    def insert_frame(self, frame_data):
        return self.collection.insert_one(frame_data)

    def vector_search(self, query_vector, filter_criteria=None, limit=10, num_candidates=100):
        # This is a placeholder for the $vectorSearch aggregation
        # Actual vector search must be done via the aggregation pipeline in MongoDB 7.0+
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self.vector_index_name,
                    "path": "detected_objects.object_embedding",
                    "queryVector": query_vector,
                    "numCandidates": num_candidates,
                    "limit": limit,
                    "filter": filter_criteria or {}
                }
            },
            {
                "$project": {
                    "video_id": 1,
                    "frame_number": 1,
                    "timestamp": 1,
                    "location": 1,
                    "minio_url": 1,
                    "detected_objects": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }
            }
        ]
        return list(self.collection.aggregate(pipeline))
