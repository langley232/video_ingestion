import numpy as np
import tritonclient.http as httpclient


class ObjectDetector:
    def __init__(self, triton_url="localhost:8002"):
        self.triton_url = triton_url
        self.model_name = "yolo"
        self.input_name = "images"
        self.output_name = "output0"
        # Class names for YOLOv8n (COCO)
        self.names = [
            'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light',
            'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
            'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
            'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard',
            'tennis racket', 'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
            'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
            'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone',
            'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear',
            'hair drier', 'toothbrush'
        ]

    def detect_objects(self, frame: np.ndarray, conf_threshold=0.3):
        # frame: np.ndarray, shape (H, W, 3), BGR
        # Triton expects (batch, 3, 640, 640) float32, RGB
        img = frame[..., ::-1]  # BGR to RGB
        img = np.transpose(img, (2, 0, 1))  # HWC to CHW
        img = img.astype(np.float32) / 255.0
        img = np.expand_dims(img, axis=0)  # Add batch dim
        client = httpclient.InferenceServerClient(url=self.triton_url)
        inputs = [httpclient.InferInput(self.input_name, img.shape, "FP32")]
        inputs[0].set_data_from_numpy(img)
        outputs = [httpclient.InferRequestedOutput(self.output_name)]
        results = client.infer(self.model_name, inputs, outputs=outputs)
        output = results.as_numpy(self.output_name)[0]  # (25200, 85)
        detections = []
        for det in output:
            conf = det[4]
            if conf < conf_threshold:
                continue
            class_scores = det[5:]
            class_id = int(np.argmax(class_scores))
            class_conf = class_scores[class_id]
            if class_conf * conf < conf_threshold:
                continue
            x, y, w, h = det[0:4]
            # Convert YOLO xywh to xyxy (assuming input 640x640)
            x1 = int((x - w / 2))
            y1 = int((y - h / 2))
            x2 = int((x + w / 2))
            y2 = int((y + h / 2))
            detection = {
                "object_type": self.names[class_id],
                "confidence": float(class_conf * conf),
                "bounding_box": [x1, y1, x2, y2]
            }
            detections.append(detection)
        return detections
