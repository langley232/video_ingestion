import os
import requests
import json
from typing import List, Dict
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SerpAPIClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("SERP_API_KEY")
        if not self.api_key:
            raise ValueError("SERP_API_KEY environment variable not set")

        self.base_url = "https://serpapi.com/search"

    def search_drone_images(self,
                            query: str,
                            category: str,
                            num_images: int = 100) -> List[Dict]:
        """
        Search for drone images using SerpAPI

        Args:
            query: Search query (e.g., "military drone", "quadcopter")
            category: Image category (military, commercial, recreational)
            num_images: Number of images to collect

        Returns:
            List of image metadata dictionaries
        """
        try:
            params = {
                "engine": "google",
                "q": query,
                "tbm": "isch",  # Image search
                "api_key": self.api_key,
                "num": num_images
            }

            response = requests.get(self.base_url, params=params)
            response.raise_for_status()

            data = response.json()
            images = data.get("images_results", [])

            # Add metadata
            processed_images = []
            for img in images:
                processed_images.append({
                    "url": img.get("original"),
                    "thumbnail": img.get("thumbnail"),
                    "title": img.get("title"),
                    "category": category,
                    "query": query,
                    "collected_at": datetime.utcnow().isoformat(),
                    "metadata": {
                        "width": img.get("original_width"),
                        "height": img.get("original_height"),
                        "source": img.get("source"),
                        "source_url": img.get("source_url")
                    }
                })

            logger.info(
                f"Collected {len(processed_images)} images for query: {query}")
            return processed_images

        except Exception as e:
            logger.error(f"Error collecting images: {str(e)}")
            return []

    def collect_training_dataset(self) -> List[Dict]:
        """
        Collect a comprehensive dataset of drone images

        Returns:
            List of all collected image metadata
        """
        queries = {
            "military": [
                "military drone",
                "UAV military",
                "combat drone",
                "surveillance drone military"
            ],
            "commercial": [
                "commercial drone",
                "delivery drone",
                "industrial drone",
                "agricultural drone"
            ],
            "recreational": [
                "quadcopter drone",
                "hobby drone",
                "racing drone",
                "toy drone"
            ]
        }

        all_images = []
        for category, category_queries in queries.items():
            for query in category_queries:
                images = self.search_drone_images(query, category)
                all_images.extend(images)

        logger.info(f"Total images collected: {len(all_images)}")
        return all_images
