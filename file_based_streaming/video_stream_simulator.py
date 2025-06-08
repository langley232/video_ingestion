import cv2
import time
import requests
import json
import os
from datetime import datetime
import threading
import random

class VideoStreamSimulator:
    def __init__(self, ingestion_endpoint="http://localhost:8000"):
        self.ingestion_endpoint = ingestion_endpoint
        self.is_streaming = False
        
    def stream_video_file(self, video_path, fps=24, loop=False):
        """Stream a video file frame by frame to simulate real-time streaming"""
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            print(f"Error: Could not open video file {video_path}")
            return
            
        frame_delay = 1.0 / fps
        frame_count = 0
        
        while True:
            ret, frame = cap.read()
            
            if not ret:
                if loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Reset to beginning
                    continue
                else:
                    break
                    
            # Encode frame as video chunk
            _, buffer = cv2.imencode('.mp4', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            video_chunk = buffer.tobytes()
            
            # Add metadata
            metadata = {
                "timestamp": datetime.now().isoformat(),
                "frame_number": frame_count,
                "latitude": 37.7749 + random.uniform(-0.01, 0.01),  # Simulate GPS drift
                "longitude": -122.4194 + random.uniform(-0.01, 0.01),
                "source": "file_stream",
                "filename": os.path.basename(video_path)
            }
            
            # Send to ingestion service
            try:
                response = requests.post(
                    f"{self.ingestion_endpoint}/ingest",
                    files={
                        "file": (f"stream_frame_{frame_count}.mp4", video_chunk, "video/mp4")
                    },
                    data={"timestamp": metadata["timestamp"]},
                    timeout=5
                )
                
                if response.status_code == 200:
                    print(f"Frame {frame_count} sent successfully")
                else:
                    print(f"Failed to send frame {frame_count}: {response.status_code}")
                    
            except Exception as e:
                print(f"Error sending frame {frame_count}: {e}")
                
            frame_count += 1
            time.sleep(frame_delay)
            
        cap.release()
        print("Video streaming completed")

    def stream_webcam(self, camera_index=0, fps=24):
        """Stream from webcam if available"""
        cap = cv2.VideoCapture(camera_index)
        
        if not cap.isOpened():
            print(f"Error: Could not open camera {camera_index}")
            return
            
        cap.set(cv2.CAP_PROP_FPS, fps)
        frame_delay = 1.0 / fps
        frame_count = 0
        
        self.is_streaming = True
        print("Starting webcam stream... Press Ctrl+C to stop")
        
        try:
            while self.is_streaming:
                ret, frame = cap.read()
                if not ret:
                    print("Failed to capture frame")
                    continue
                    
                # Encode frame
                _, buffer = cv2.imencode('.jpg', frame)
                
                # Convert to mp4-like chunk (you might need to adjust this)
                video_chunk = buffer.tobytes()
                
                metadata = {
                    "timestamp": datetime.now().isoformat(),
                    "frame_number": frame_count,
                    "latitude": 37.7749 + random.uniform(-0.005, 0.005),
                    "longitude": -122.4194 + random.uniform(-0.005, 0.005),
                    "source": "webcam_stream"
                }
                
                try:
                    response = requests.post(
                        f"{self.ingestion_endpoint}/ingest",
                        files={
                            "file": (f"webcam_frame_{frame_count}.jpg", video_chunk, "image/jpeg")
                        },
                        data={"timestamp": metadata["timestamp"]},
                        timeout=2
                    )
                    
                    if response.status_code == 200:
                        print(f"Webcam frame {frame_count} sent")
                    
                except Exception as e:
                    print(f"Error sending webcam frame: {e}")
                    
                frame_count += 1
                time.sleep(frame_delay)
                
        except KeyboardInterrupt:
            print("Stopping webcam stream...")
            
        finally:
            self.is_streaming = False
            cap.release()

if __name__ == "__main__":
    simulator = VideoStreamSimulator("http://localhost:8000")
    
    # Example usage:
    # simulator.stream_video_file("path/to/your/video.mp4", fps=24, loop=True)
    # simulator.stream_webcam(camera_index=0, fps=24)
