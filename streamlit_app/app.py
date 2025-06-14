import streamlit as st
import io
import json
import requests
from datetime import datetime
from minio import Minio
import os

# Configuration
INGESTION_ENDPOINT = os.getenv("INGESTION_ENDPOINT", "http://ingestion:8000")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
bucket_name = "videos"

# Initialize MinIO client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)


def get_video_metadata():
    try:
        response = minio_client.list_objects(bucket_name, prefix="metadata/")
        metadata_files = [obj.object_name for obj in response]

        all_metadata = []
        for metadata_file in metadata_files:
            try:
                response = minio_client.get_object(bucket_name, metadata_file)
                metadata = json.loads(response.read().decode())
                response.close()
                response.release_conn()

                # Add file name and path
                metadata['file_name'] = metadata_file.replace(
                    "metadata/", "").replace(".json", "")
                metadata['video_path'] = f"generated_videos/{metadata['file_name']}.mp4"

                all_metadata.append(metadata)
            except Exception as e:
                st.error(
                    f"Error reading metadata file {metadata_file}: {str(e)}")
                continue

        return all_metadata
    except Exception as e:
        st.error(f"Error listing metadata files: {str(e)}")
        return []


def search_videos(metadata_list, search_params):
    results = []
    for metadata in metadata_list:
        matches = True

        # Time range search
        if search_params.get('start_date') and search_params.get('end_date'):
            video_date = datetime.strptime(
                metadata['timestamp'], "%Y-%m-%d %H:%M:%S")
            if not (search_params['start_date'] <= video_date <= search_params['end_date']):
                matches = False

        # Location search
        if search_params.get('location_name'):
            if search_params['location_name'].lower() not in metadata['location_name'].lower():
                matches = False

        # Description search
        if search_params.get('description'):
            if search_params['description'].lower() not in metadata['description'].lower():
                matches = False

        if matches:
            results.append(metadata)

    return results


def main():
    st.title("Video Ingestion System")

    # Add tabs for different functionalities
    tab1, tab2 = st.tabs(["Upload Video", "Search Videos"])

    with tab1:
        st.header("Upload Video")
        uploaded_file = st.file_uploader(
            "Choose a video file", type=["mp4", "avi", "mov"])

        if uploaded_file is not None:
            # Display video
            video_bytes = uploaded_file.read()
            st.video(video_bytes)

            # Add metadata input fields
            col1, col2 = st.columns(2)
            with col1:
                latitude = st.number_input(
                    "Latitude", value=40.7829, format="%.4f")
                longitude = st.number_input(
                    "Longitude", value=-73.9654, format="%.4f")
            with col2:
                location_name = st.text_input(
                    "Location Name", value="Central Park")
                description = st.text_area("Description", value="")

            if st.button("Process Video"):
                with st.spinner("Processing video..."):
                    try:
                        # Save to MinIO
                        minio_client.put_object(
                            bucket_name,
                            f"generated_videos/{uploaded_file.name}",
                            io.BytesIO(video_bytes),
                            len(video_bytes)
                        )

                        # Send to ingestion service
                        response = requests.post(
                            f"{INGESTION_ENDPOINT}/ingest",
                            json={
                                "video_path": f"generated_videos/{uploaded_file.name}",
                                "latitude": latitude,
                                "longitude": longitude,
                                "location_name": location_name,
                                "description": description
                            }
                        )

                        if response.status_code == 200:
                            st.success("Video processed successfully!")
                        else:
                            st.error(
                                f"Error processing video: {response.text}")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

    with tab2:
        st.header("Search Videos")

        # Search filters
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date")
            end_date = st.date_input("End Date")
        with col2:
            location_name = st.text_input("Location Name")
            description = st.text_input("Description")

        if st.button("Search"):
            metadata_list = get_video_metadata()
            if metadata_list:
                search_params = {
                    'start_date': datetime.combine(start_date, datetime.min.time()),
                    'end_date': datetime.combine(end_date, datetime.max.time()),
                    'location_name': location_name,
                    'description': description
                }

                results = search_videos(metadata_list, search_params)

                if results:
                    st.success(f"Found {len(results)} videos")
                    for metadata in results:
                        with st.expander(f"Video: {metadata['file_name']}"):
                            st.write(
                                f"**Location:** {metadata['location_name']}")
                            st.write(f"**Timestamp:** {metadata['timestamp']}")
                            st.write(
                                f"**Description:** {metadata['description']}")

                            # Display video if available
                            try:
                                response = minio_client.get_object(
                                    bucket_name, metadata['video_path'])
                                video_bytes = response.read()
                                response.close()
                                response.release_conn()
                                st.video(video_bytes)
                            except Exception as e:
                                st.error(f"Error loading video: {str(e)}")
                else:
                    st.info("No videos found matching the search criteria")
            else:
                st.warning("No videos found in the system")


if __name__ == "__main__":
    main()
