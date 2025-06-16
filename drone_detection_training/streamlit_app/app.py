import streamlit as st
import requests
import json
from typing import List, Dict
import os

# Configure the page
st.set_page_config(
    page_title="Drone Detection Training",
    page_icon="🛸",
    layout="wide"
)

# Constants
IMAGE_COLLECTOR_API = os.getenv(
    "IMAGE_COLLECTOR_API", "http://image-collector:8000")
FINE_TUNING_API = os.getenv("FINE_TUNING_API", "http://fine-tuning:8000")
MODEL_MANAGER_API = os.getenv("MODEL_MANAGER_API", "http://model-manager:8000")

# Helper functions


def collect_images(query: str, category: str, num_images: int) -> Dict:
    """Collect images using the API"""
    response = requests.post(
        f"{IMAGE_COLLECTOR_API}/collect-images",
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
        f"{IMAGE_COLLECTOR_API}/collect-dataset",
        json={"categories": categories}
    )
    response.raise_for_status()
    return response.json()


def prepare_dataset(config: Dict) -> Dict:
    """Prepare dataset for training"""
    response = requests.post(
        f"{FINE_TUNING_API}/prepare-dataset",
        json=config
    )
    response.raise_for_status()
    return response.json()


def train_model(config: Dict) -> Dict:
    """Train the model"""
    response = requests.post(
        f"{FINE_TUNING_API}/train",
        json=config
    )
    response.raise_for_status()
    return response.json()


def list_models() -> Dict:
    """List available models"""
    response = requests.get(f"{MODEL_MANAGER_API}/models")
    response.raise_for_status()
    return response.json()


def deploy_model(model_name: str, version: str = None) -> Dict:
    """Deploy model to Ollama"""
    response = requests.post(
        f"{MODEL_MANAGER_API}/deploy",
        json={"model_name": model_name, "version": version}
    )
    response.raise_for_status()
    return response.json()


# Title and description
st.title("🛸 Drone Detection Training")
st.markdown("""
This tool helps you collect drone images, fine-tune the Moondream model, and deploy it to Ollama.
Use the tabs below to navigate through different stages of the process.
""")

# Create tabs
tab1, tab2, tab3 = st.tabs(
    ["Image Collection", "Model Training", "Model Deployment"])

# Image Collection Tab
with tab1:
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
            category = st.selectbox(
                "Category",
                ["military_drones", "commercial_drones", "recreational_drones"]
            )

        with col2:
            num_images = st.slider(
                "Number of images",
                min_value=10,
                max_value=500,
                value=100,
                step=10
            )

        if st.button("Collect Images", type="primary"):
            with st.spinner("Collecting images..."):
                try:
                    result = collect_images(query, category, num_images)
                    st.success(
                        f"Successfully collected {result['stored_images']} images!")
                    st.json(result)
                except Exception as e:
                    st.error(f"Error collecting images: {str(e)}")

    else:
        # Full dataset collection
        st.subheader("Full Dataset Collection")
        st.info(
            "This will collect images for all selected categories using predefined queries.")

        selected_categories = st.multiselect(
            "Select categories",
            ["military_drones", "commercial_drones", "recreational_drones"],
            default=["military_drones",
                     "commercial_drones", "recreational_drones"]
        )

        if st.button("Collect Full Dataset", type="primary"):
            with st.spinner("Collecting full dataset..."):
                try:
                    result = collect_dataset(selected_categories)
                    st.success("Successfully collected full dataset!")
                    st.json(result["dataset_metadata"])
                except Exception as e:
                    st.error(f"Error collecting dataset: {str(e)}")

# Model Training Tab
with tab2:
    st.header("Model Training")

    # Training configuration
    st.subheader("Training Configuration")

    col1, col2 = st.columns(2)

    with col1:
        epochs = st.slider("Number of epochs", 1, 10, 3)
        batch_size = st.slider("Batch size", 4, 32, 8, 4)

    with col2:
        learning_rate = st.number_input(
            "Learning rate",
            min_value=1e-6,
            max_value=1e-3,
            value=1e-5,
            format="%.6f"
        )
        categories = st.multiselect(
            "Categories to train on",
            ["military_drones", "commercial_drones", "recreational_drones"],
            default=["military_drones",
                     "commercial_drones", "recreational_drones"]
        )

    # Training steps
    st.subheader("Training Steps")

    if st.button("1. Prepare Dataset", type="primary"):
        with st.spinner("Preparing dataset..."):
            try:
                result = prepare_dataset({
                    "categories": categories,
                    "batch_size": batch_size
                })
                st.success("Dataset prepared successfully!")
                st.json(result)
            except Exception as e:
                st.error(f"Error preparing dataset: {str(e)}")

    if st.button("2. Train Model", type="primary"):
        with st.spinner("Training model..."):
            try:
                result = train_model({
                    "epochs": epochs,
                    "batch_size": batch_size,
                    "learning_rate": learning_rate,
                    "categories": categories
                })
                st.success("Model trained successfully!")
                st.json(result["training_results"])
            except Exception as e:
                st.error(f"Error training model: {str(e)}")

# Model Deployment Tab
with tab3:
    st.header("Model Deployment")

    # List available models
    st.subheader("Available Models")

    try:
        models = list_models()
        if models["models"]:
            model_names = [model["name"] for model in models["models"]]
            selected_model = st.selectbox(
                "Select model to deploy", model_names)

            if st.button("Deploy Model", type="primary"):
                with st.spinner("Deploying model..."):
                    try:
                        result = deploy_model(selected_model)
                        st.success("Model deployed successfully!")
                        st.json(result)
                    except Exception as e:
                        st.error(f"Error deploying model: {str(e)}")
        else:
            st.info("No models available. Please train a model first.")
    except Exception as e:
        st.error(f"Error listing models: {str(e)}")

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center'>
    <p>Drone Detection Training Tool | Powered by Moondream</p>
</div>
""", unsafe_allow_html=True)
