import cv2
import time
import requests
import threading
import os
from datetime import datetime

class WebcamStreamer:
    def __init__(self, camera_id=0, ingestion_endpoint="http://localhost:8000"):
        self.camera_id = camera_id
        self.ingestion_endpoint = ingestion_endpoint
        self.cap = None
        self.streaming = False
        self.frame_rate = 30  # FPS
        self.chunk_duration = 5  # seconds per video chunk
        
    def start_streaming(self):
        """Start capturing and streaming video chunks"""
        self.cap = cv2.VideoCapture(self.camera_id)
        if not self.cap.isOpened():
            print(f"Error: Could not open camera {self.camera_id}")
            return
            
        self.cap.set(cv2.CAP_PROP_FPS, self.frame_rate)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.streaming = True
        print(f"Started streaming from camera {self.camera_id}")
        
        while self.streaming:
            self.capture_and_send_chunk()
            time.sleep(1)  # Brief pause between chunks
            
    def capture_and_send_chunk(self):
        """Capture a video chunk and send to ingestion"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        temp_filename = f"/tmp/stream_chunk_{int(time.time())}.mp4"
        
        # Video writer setup
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_filename, fourcc, self.frame_rate, (640, 480))
        
        frames_to_capture = self.frame_rate * self.chunk_duration
        frames_captured = 0
        
        print(f"Capturing {frames_to_capture} frames...")
        
        while frames_captured < frames_to_capture and self.streaming:
            ret, frame = self.cap.read()
            if not ret:
                print("Failed to capture frame")
                break
                
            out.write(frame)
            frames_captured += 1
            
            # Optional: Display frame (comment out for headless)
            # cv2.imshow('Streaming', frame)
            # if cv2.waitKey(1) & 0xFF == ord('q'):
            #     self.streaming = False
            #     break
                
        out.release()
        
        if frames_captured > 0:
            self.send_to_ingestion(temp_filename, timestamp)
        
        # Cleanup
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
            
    def send_to_ingestion(self, video_path, timestamp):
        """Send video chunk to ingestion service"""
        try:
            with open(video_path, 'rb') as f:
                files = {'file': ('stream_chunk.mp4', f, 'video/mp4')}
                data = {'timestamp': timestamp}
                
                response = requests.post(
                    f"{self.ingestion_endpoint}/ingest",
                    files=files,
                    data=data,
                    timeout=30
                )
                
                if response.status_code == 200:
                    print(f"✓ Chunk sent successfully at {timestamp}")
                else:
                    print(f"✗ Failed to send chunk: {response.status_code}")
                    
        except Exception as e:
            print(f"Error sending chunk: {e}")
            
    def stop_streaming(self):
        """Stop streaming"""
        self.streaming = False
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
        print("Streaming stopped")

if __name__ == "__main__":
    streamer = WebcamStreamer(
        camera_id=0,  # Change if you have multiple cameras
        ingestion_endpoint="http://localhost:8000"
    )
    
    try:
        streamer.start_streaming()
    except KeyboardInterrupt:
        streamer.stop_streaming()
