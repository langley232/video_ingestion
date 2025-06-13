import cv2
import time
import requests
import os
import random
from datetime import datetime, timedelta
import threading
import glob

class FileVideoStreamer:
    def __init__(self, video_dir="./test_videos", ingestion_endpoint="http://localhost:8000"):
        self.video_dir = video_dir
        self.ingestion_endpoint = ingestion_endpoint
        self.streaming = False
        self.chunk_duration = 10  # seconds per chunk
        
    def get_video_files(self):
        """Get all video files from directory"""
        patterns = ['*.mp4', '*.avi', '*.mov', '*.mkv']
        video_files = []
        for pattern in patterns:
            video_files.extend(glob.glob(os.path.join(self.video_dir, pattern)))
        return video_files
        
    def simulate_live_locations(self):
        """Generate realistic GPS coordinates (simulating moving camera)"""
        # Base locations (you can customize these)
        base_locations = [
            (37.7749, -122.4194),  # San Francisco
            (40.7128, -74.0060),   # New York
            (34.0522, -118.2437),  # Los Angeles
            (51.5074, -0.1278),    # London
        ]
        
        base_lat, base_lon = random.choice(base_locations)
        
        # Add small random movement (simulating drone/camera movement)
        lat_offset = random.uniform(-0.01, 0.01)
        lon_offset = random.uniform(-0.01, 0.01)
        
        return base_lat + lat_offset, base_lon + lon_offset
        
    def start_streaming(self):
        """Start continuous streaming from video files"""
        video_files = self.get_video_files()
        
        if not video_files:
            print(f"No video files found in {self.video_dir}")
            return
            
        print(f"Found {len(video_files)} video files")
        self.streaming = True
        
        while self.streaming:
            video_file = random.choice(video_files)
            print(f"Streaming from: {os.path.basename(video_file)}")
            self.stream_video_file(video_file)
            
            if self.streaming:
                time.sleep(2)  # Brief pause between videos
                
    def stream_video_file(self, video_path):
        """Stream chunks from a single video file"""
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            print(f"Could not open video: {video_path}")
            return
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if fps <= 0:
            fps = 30  # Default FPS
            
        frames_per_chunk = int(fps * self.chunk_duration)
        current_frame = 0
        
        print(f"Video FPS: {fps}, Total frames: {total_frames}")
        
        while current_frame < total_frames and self.streaming:
            chunk_frames = []
            frames_read = 0
            
            # Read frames for current chunk
            while frames_read < frames_per_chunk and current_frame < total_frames:
                ret, frame = cap.read()
                if not ret:
                    break
                    
                chunk_frames.append(frame)
                frames_read += 1
                current_frame += 1
                
            if chunk_frames:
                self.create_and_send_chunk(chunk_frames, fps)
                
            # Simulate real-time streaming delay
            time.sleep(self.chunk_duration * 0.5)  # 50% of chunk duration
            
        cap.release()
        
    def create_and_send_chunk(self, frames, fps):
        """Create video chunk from frames and send to ingestion"""
        if not frames:
            return
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        temp_filename = f"/tmp/file_stream_chunk_{int(time.time())}.mp4"
        
        # Get frame dimensions
        height, width = frames[0].shape[:2]
        
        # Create video writer
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_filename, fourcc, fps, (width, height))
        
        # Write frames
        for frame in frames:
            out.write(frame)
            
        out.release()
        
        # Send to ingestion with simulated GPS data
        self.send_to_ingestion(temp_filename, timestamp)
        
        # Cleanup
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
            
    def send_to_ingestion(self, video_path, timestamp):
        """Send video chunk to ingestion service with metadata"""
        try:
            lat, lon = self.simulate_live_locations()
            
            with open(video_path, 'rb') as f:
                files = {'file': ('live_stream.mp4', f, 'video/mp4')}
                data = {
                    'timestamp': timestamp,
                    'latitude': str(lat),
                    'longitude': str(lon),
                    'source': 'file_stream'
                }
                
                response = requests.post(
                    f"{self.ingestion_endpoint}/ingest",
                    files=files,
                    data=data,
                    timeout=30
                )
                
                if response.status_code == 200:
                    print(f"✓ Chunk sent: {timestamp} | Location: ({lat:.4f}, {lon:.4f})")
                else:
                    print(f"✗ Failed to send chunk: {response.status_code}")
                    
        except Exception as e:
            print(f"Error sending chunk: {e}")
            
    def stop_streaming(self):
        """Stop streaming"""
        self.streaming = False
        print("File streaming stopped")

# Batch video downloader for testing
class VideoDownloader:
    def __init__(self, output_dir="./test_videos"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
    def download_sample_videos(self):
        """Download sample videos for testing"""
        sample_urls = [
            "https://sample-videos.com/zip/10/mp4/SampleVideo_1280x720_1mb.mp4",
            "https://www.learningcontainer.com/wp-content/uploads/2020/05/sample-mp4-file.mp4",
        ]
        
        for i, url in enumerate(sample_urls):
            try:
                response = requests.get(url, timeout=60)
                if response.status_code == 200:
                    filename = f"sample_video_{i+1}.mp4"
                    filepath = os.path.join(self.output_dir, filename)
                    
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    print(f"Downloaded: {filename}")
                    
            except Exception as e:
                print(f"Failed to download {url}: {e}")

if __name__ == "__main__":
    # Option 1: Download sample videos first
    downloader = VideoDownloader()
    downloader.download_sample_videos()
    
    # Option 2: Start streaming
    streamer = FileVideoStreamer(
        video_dir="./test_videos",
        ingestion_endpoint="http://localhost:8000"
    )
    
    try:
        streamer.start_streaming()
    except KeyboardInterrupt:
        streamer.stop_streaming()
