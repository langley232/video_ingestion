import cv2
import subprocess
import threading
import time
import requests
import json
from datetime import datetime
import os

class RTMPStreamProcessor:
    def __init__(self, rtmp_url, ingestion_endpoint):
        self.rtmp_url = rtmp_url
        self.ingestion_endpoint = ingestion_endpoint
        self.is_processing = False
        
    def process_rtmp_stream(self, stream_key="test", chunk_duration=5):
        """Process RTMP stream and send chunks to ingestion service"""
        rtmp_input = f"{self.rtmp_url}/{stream_key}"
        
        # Use FFmpeg to capture RTMP stream
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', rtmp_input,
            '-f', 'segment',
            '-segment_time', str(chunk_duration),
            '-segment_format', 'mp4',
            '-reset_timestamps', '1',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            f'/app/streams/chunk_%03d.mp4'
        ]
        
        self.is_processing = True
        
        try:
            # Start FFmpeg process
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Monitor for new chunk files
            chunk_monitor_thread = threading.Thread(
                target=self._monitor_chunks,
                args=('/app/streams',)
            )
            chunk_monitor_thread.start()
            
            # Wait for process
            process.wait()
            
        except Exception as e:
            print(f"Error processing RTMP stream: {e}")
        finally:
            self.is_processing = False
            
    def _monitor_chunks(self, chunk_dir):
        """Monitor directory for new video chunks and send them"""
        processed_chunks = set()
        
        while self.is_processing:
            try:
                files = [f for f in os.listdir(chunk_dir) if f.endswith('.mp4')]
                
                for file in files:
                    if file not in processed_chunks:
                        file_path = os.path.join(chunk_dir, file)
                        
                        # Wait for file to be completely written
                        time.sleep(1)
                        
                        # Send chunk to ingestion service
                        self._send_chunk(file_path)
                        processed_chunks.add(file)
                        
                        # Clean up old chunk
                        os.remove(file_path)
                        
            except Exception as e:
                print(f"Error monitoring chunks: {e}")
                
            time.sleep(2)
            
    def _send_chunk(self, chunk_path):
        """Send video chunk to ingestion service"""
        try:
            with open(chunk_path, 'rb') as f:
                video_data = f.read()
                
            metadata = {
                "timestamp": datetime.now().isoformat(),
                "source": "rtmp_stream",
                "chunk_file": os.path.basename(chunk_path)
            }
            
            response = requests.post(
                f"{self.ingestion_endpoint}/ingest",
                files={
                    "file": (os.path.basename(chunk_path), video_data, "video/mp4")
                },
                data={"timestamp": metadata["timestamp"]},
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"Successfully sent chunk: {os.path.basename(chunk_path)}")
            else:
                print(f"Failed to send chunk: {response.status_code}")
                
        except Exception as e:
            print(f"Error sending chunk {chunk_path}: {e}")

# Usage example
if __name__ == "__main__":
    processor = RTMPStreamProcessor(
        rtmp_url="rtmp://nginx-rtmp:1935/live",
        ingestion_endpoint="http://ingestion:8000"
    )
    
    processor.process_rtmp_stream(stream_key="drone_feed", chunk_duration=10)
