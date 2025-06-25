import tritonclient.http as httpclient
import numpy as np

# Updated Triton URL - note the port change from 8002 to 8004
# to avoid conflicts with other services in the main docker-compose.yml
TRITON_URL = "localhost:8004"

# Example: YOLOv8n inference
# Input: (batch, 3, 640, 640) float32
# Output: (batch, 25200, 85) float32


def infer_yolo(image_np):
    client = httpclient.InferenceServerClient(url=TRITON_URL)
    inputs = [httpclient.InferInput("images", image_np.shape, "FP32")]
    inputs[0].set_data_from_numpy(image_np)
    outputs = [httpclient.InferRequestedOutput("output0")]
    results = client.infer("yolo", inputs, outputs=outputs)
    return results.as_numpy("output0")

# Example: CLIP inference
# Input: (batch, 3, 224, 224) float32
# Output: (batch, 512) float32


def infer_clip(image_np):
    client = httpclient.InferenceServerClient(url=TRITON_URL)
    inputs = [httpclient.InferInput("input", image_np.shape, "FP32")]
    inputs[0].set_data_from_numpy(image_np)
    outputs = [httpclient.InferRequestedOutput("embeddings")]
    results = client.infer("clip", inputs, outputs=outputs)
    return results.as_numpy("embeddings")


if __name__ == "__main__":
    # Dummy test
    yolo_input = np.random.rand(1, 3, 640, 640).astype(np.float32)
    yolo_out = infer_yolo(yolo_input)
    print("YOLO output shape:", yolo_out.shape)

    clip_input = np.random.rand(1, 3, 224, 224).astype(np.float32)
    clip_out = infer_clip(clip_input)
    print("CLIP output shape:", clip_out.shape)
