import streamlit as st
import requests
import os
import tempfile
from datetime import datetime
import time
import subprocess
import sys

# Health check endpoint for Docker


def health_check():
    """Simple health check for Docker healthcheck"""
    try:
        # Check if backend is accessible
        backend_url = os.getenv("BACKEND_URL", "http://backend:8000")
        response = requests.get(f"{backend_url}/health/", timeout=5)
        if response.status_code == 200:
            return True
    except:
        pass
    return False


# Run health check if called directly
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        if health_check():
            sys.exit(0)
        else:
            sys.exit(1)

# Streamlit app configuration
st.set_page_config(page_title="Text-to-Speech with ElevenLabs", page_icon="🎙️")

# Backend API URL (set via environment variable or default to localhost)
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

# Streamlit app
st.title("🎙️ Text-to-Speech with ElevenLabs")
st.markdown("Enter text and generate audio using the ElevenLabs API.")

# Initialize session state for voices
if 'voices_loaded' not in st.session_state:
    st.session_state.voices_loaded = False
    st.session_state.voice_options = {}

# Function to fetch voices with error handling


def fetch_voices():
    try:
        with st.spinner("Loading available voices..."):
            response = requests.get(f"{BACKEND_URL}/voices", timeout=10)
            response.raise_for_status()
            voices = response.json()
            voice_options = {voice["name"]: voice["voice_id"]
                             for voice in voices}
            st.session_state.voice_options = voice_options
            st.session_state.voices_loaded = True
            return True
    except requests.RequestException as e:
        st.error(f"Failed to fetch voices: {e}")
        st.session_state.voice_options = {
            "Rachel": "21m00Tcm4TlvDq8ikWAM"}  # Fallback
        st.session_state.voices_loaded = True
        return False


# Load voices if not already loaded
if not st.session_state.voices_loaded:
    fetch_voices()

# Add a refresh button for voices
col1, col2 = st.columns([3, 1])
with col2:
    if st.button("🔄 Refresh Voices"):
        st.session_state.voices_loaded = False
        fetch_voices()
        st.rerun()

# Check if backend is accessible


def check_backend_health():
    try:
        response = requests.get(f"{BACKEND_URL}/voices", timeout=5)
        return response.status_code == 200
    except:
        return False


# Display backend status
if check_backend_health():
    st.success("✅ Backend is connected")
else:
    st.error("❌ Backend is not accessible. Please check your backend service.")
    st.info(f"Backend URL: {BACKEND_URL}")

# Input form
with st.form("tts_form"):
    text_input = st.text_area(
        "Text to Convert",
        "Hello! This is a test of the ElevenLabs text-to-speech API.",
        height=100,
        help="Enter the text you want to convert to speech (max 5000 characters)"
    )

    # Character count
    char_count = len(text_input)
    if char_count > 5000:
        st.error(
            f"Text is too long ({char_count} characters). Please keep it under 5000 characters.")
    else:
        st.info(f"Character count: {char_count}/5000")

    voice_name = st.selectbox(
        "Select Voice",
        list(st.session_state.voice_options.keys()),
        index=0,
        help="Choose from available ElevenLabs voices"
    )

    # Advanced settings in an expander
    with st.expander("Advanced Settings"):
        model_id = st.selectbox(
            "Model",
            ["eleven_turbo_v2_5", "eleven_monolingual_v1", "eleven_multilingual_v2"],
            index=0,
            help="Choose the ElevenLabs model to use"
        )
        stability = st.slider(
            "Stability",
            0.0, 1.0, 0.5, 0.01,
            help="Higher values make the voice more consistent but potentially monotonous"
        )
        similarity_boost = st.slider(
            "Similarity Boost",
            0.0, 1.0, 0.75, 0.01,
            help="Higher values make the voice more similar to the original speaker"
        )

    submit_button = st.form_submit_button(
        "🎵 Generate Audio", use_container_width=True)

# Handle form submission
if submit_button:
    if not text_input.strip():
        st.error("Please enter some text to convert.")
    elif len(text_input) > 5000:
        st.error("Text is too long. Please keep it under 5000 characters.")
    else:
        # Prepare request payload
        payload = {
            "text": text_input.strip(),
            "voice_id": st.session_state.voice_options[voice_name],
            "model_id": model_id,
            "stability": stability,
            "similarity_boost": similarity_boost
        }

        # Send request to backend
        try:
            start_time = time.time()
            with st.spinner("Generating audio... This may take a few seconds."):
                response = requests.post(
                    f"{BACKEND_URL}/synthesize/",
                    json=payload,
                    stream=True,
                    timeout=30  # 30 second timeout
                )
                response.raise_for_status()

                # Use temporary file instead of saving to current directory
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            tmp_file.write(chunk)
                    temp_file_path = tmp_file.name

                generation_time = time.time() - start_time

                # Display success message with generation time
                st.success(
                    f"✅ Audio generated successfully in {generation_time:.2f} seconds!")

                # Display audio player
                with open(temp_file_path, "rb") as audio_file:
                    audio_bytes = audio_file.read()
                    st.audio(audio_bytes, format="audio/mp3")

                # Provide download link with a meaningful filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"tts_audio_{voice_name}_{timestamp}.mp3"

                st.download_button(
                    label="📥 Download Audio",
                    data=audio_bytes,
                    file_name=filename,
                    mime="audio/mp3",
                    use_container_width=True
                )

                # Display generation info
                with st.expander("Generation Details"):
                    st.write(f"**Voice:** {voice_name}")
                    st.write(f"**Model:** {model_id}")
                    st.write(f"**Stability:** {stability}")
                    st.write(f"**Similarity Boost:** {similarity_boost}")
                    st.write(f"**Text Length:** {len(text_input)} characters")
                    st.write(
                        f"**Generation Time:** {generation_time:.2f} seconds")

                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass  # Ignore cleanup errors

        except requests.Timeout:
            st.error(
                "⏰ Request timed out. The text might be too long or the server is busy. Please try again.")
        except requests.RequestException as e:
            st.error(f"❌ Failed to generate audio: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    st.error(
                        f"Server error: {error_detail.get('detail', 'Unknown error')}")
                except:
                    st.error(
                        f"HTTP {e.response.status_code}: {e.response.text}")

# Footer
st.markdown("---")
st.markdown("Built with ❤️ using Streamlit and ElevenLabs API")
