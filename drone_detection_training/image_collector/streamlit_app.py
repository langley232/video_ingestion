import streamlit as st
import requests
import json
from typing import List, Dict
import os

# Configure the page
st.set_page_config(
    page_title="Drone Image Collection",
    page_icon="🛸",
    layout="wide"
)

# Constants
API_URL = os.getenv("API_URL", "http://localhost:8000")
CATEGORIES = [
    "military_drones",
    "commercial_drones",
    "recreational_drones"
]


def collect_images(query: str, category: str, num_images: int) -> Dict:
    """Collect images using the API"""
    response = requests.post(
        f"{API_URL}/collect-images",
        json={
            "query": query,
            "category": category,
            "num_images": num_images
        }
    )
    response.raise_for_status()
    return response.json()


def collect_dataset(categories: List[str] = None) -> Dict:
    """Collect full dataset using the API"""
    response = requests.post(
        f"{API_URL}/collect-dataset",
        json={"categories": categories}
    )
    response.raise_for_status()
    return response.json()


# Title and description
st.title("🛸 Drone Image Collection")
st.markdown("""
This tool helps collect drone images for training the Moondream model.
Use the sidebar to configure your image collection parameters.
""")

# Sidebar configuration
st.sidebar.header("Configuration")

# Category selection
selected_categories = st.sidebar.multiselect(
    "Select drone categories",
    CATEGORIES,
    default=CATEGORIES
)

# Number of images
num_images = st.sidebar.slider(
    "Number of images per category",
    min_value=10,
    max_value=500,
    value=100,
    step=10
)

# Main content
st.header("Image Collection")

# Collection mode selection
collection_mode = st.radio(
    "Select collection mode",
    ["Single Query", "Full Dataset"],
    horizontal=True
)

if collection_mode == "Single Query":
    # Single query collection
    st.subheader("Single Query Collection")

    col1, col2 = st.columns(2)

    with col1:
        query = st.text_input("Search query", "drone flying in sky")
        category = st.selectbox("Category", CATEGORIES)

    with col2:
        if st.button("Collect Images", type="primary"):
            with st.spinner("Collecting images..."):
                try:
                    result = collect_images(query, category, num_images)
                    st.success(
                        f"Successfully collected {result['stored_images']} images!")

                    # Display results
                    st.json(result)

                except Exception as e:
                    st.error(f"Error collecting images: {str(e)}")

else:
    # Full dataset collection
    st.subheader("Full Dataset Collection")
    st.info(
        "This will collect images for all selected categories using predefined queries.")

    if st.button("Collect Full Dataset", type="primary"):
        with st.spinner("Collecting full dataset..."):
            try:
                result = collect_dataset(selected_categories)
                st.success("Successfully collected full dataset!")

                # Display dataset metadata
                st.json(result["dataset_metadata"])

            except Exception as e:
                st.error(f"Error collecting dataset: {str(e)}")

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center'>
    <p>Drone Image Collection Tool | Powered by SerpAPI</p>
</div>
""", unsafe_allow_html=True)
