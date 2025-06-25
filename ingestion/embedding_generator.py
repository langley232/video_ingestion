import numpy as np
import tritonclient.http as httpclient
import os


class EmbeddingGenerator:
    def __init__(self, triton_url=None):
        self.triton_url = triton_url or os.getenv(
            "TRITON_ENDPOINT", "localhost:8002")
        self.model_name = "clip"
        self.input_name = "input"
        self.output_name = "embeddings"

    def generate_embedding(self, image: np.ndarray) -> np.ndarray:
        # image: np.ndarray, shape (H, W, 3), BGR
        # Triton expects (batch, 3, 224, 224) float32, RGB
        img = image[..., ::-1]  # BGR to RGB
        img = np.transpose(img, (2, 0, 1))  # HWC to CHW
        img = img.astype(np.float32) / 255.0
        img = np.expand_dims(img, axis=0)  # Add batch dim
        client = httpclient.InferenceServerClient(url=self.triton_url)
        inputs = [httpclient.InferInput(self.input_name, img.shape, "FP32")]
        inputs[0].set_data_from_numpy(img)
        outputs = [httpclient.InferRequestedOutput(self.output_name)]
        results = client.infer(self.model_name, inputs, outputs=outputs)
        embedding = results.as_numpy(self.output_name)
        return embedding.flatten()
