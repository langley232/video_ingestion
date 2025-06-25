import os
import shutil
import subprocess
from urllib.request import urlretrieve
from ultralytics import YOLO

TRITON_MODELS_DIR = os.getenv("TRITON_MODELS_DIR", "triton_models")
YOLO_MODEL_PATH = "yolov8n.pt"
YOLO_MODEL_NAME = "yolo"
YOLO_INPUT_SHAPE = [3, 640, 640]
YOLO_OUTPUT_SHAPE = [25200, 85]
YOLO_ONNX_PATH = os.path.join(
    TRITON_MODELS_DIR, YOLO_MODEL_NAME, "1", "model.onnx")
YOLO_WEIGHTS_URL = "https://github.com/ultralytics/assets/releases/download/v8.0.0/yolov8n.pt"

CLIP_MODEL_PATH = "clip-vit-b-16.onnx"
CLIP_MODEL_NAME = "clip"
CLIP_INPUT_SHAPE = [3, 224, 224]
CLIP_OUTPUT_SHAPE = [512]
CLIP_ONNX_URL = "https://huggingface.co/monster-labs/clip-vit-base-patch16-onnx/resolve/main/model.onnx"
CLIP_ONNX_PATH = os.path.join(
    TRITON_MODELS_DIR, CLIP_MODEL_NAME, "1", "model.onnx")


def download_file(url, dest):
    if not os.path.exists(dest):
        print(f"Downloading {url} to {dest}...")
        urlretrieve(url, dest)
    else:
        print(f"File {dest} already exists.")


def export_yolo_to_onnx(model_path, export_dir, imgsz=640):
    print("Exporting YOLOv8n to ONNX...")
    model = YOLO(model_path)
    onnx_path = os.path.join(export_dir, "model.onnx")
    model.export(format='onnx', imgsz=imgsz, dynamic=True,
                 simplify=True, opset=12, output=onnx_path)
    return onnx_path


def create_triton_repo(model_name, onnx_path, input_name, input_shape, output_name, output_shape):
    repo_dir = os.path.join(TRITON_MODELS_DIR, model_name, "1")
    os.makedirs(repo_dir, exist_ok=True)
    shutil.copy(onnx_path, os.path.join(repo_dir, "model.onnx"))
    config_path = os.path.join(TRITON_MODELS_DIR, model_name, "config.pbtxt")
    with open(config_path, "w") as f:
        f.write(f'''
name: "{model_name}"
platform: "onnxruntime_onnx"
max_batch_size: 8
input [
  {{
    name: "{input_name}"
    data_type: TYPE_FP32
    dims: {input_shape}
  }}
]
output [
  {{
    name: "{output_name}"
    data_type: TYPE_FP32
    dims: {output_shape}
  }}
]
''')


def main():
    print("🚀 Starting Triton model preparation...")

    # Download YOLOv8n weights if missing
    download_file(YOLO_WEIGHTS_URL, YOLO_MODEL_PATH)
    # Download CLIP ONNX if missing
    download_file(CLIP_ONNX_URL, CLIP_MODEL_PATH)

    # Export YOLOv8n to ONNX and create Triton repo
    yolo_onnx_path = export_yolo_to_onnx(
        YOLO_MODEL_PATH, os.path.join(TRITON_MODELS_DIR, YOLO_MODEL_NAME, "1"))
    create_triton_repo(YOLO_MODEL_NAME, yolo_onnx_path, "images",
                       YOLO_INPUT_SHAPE, "output0", YOLO_OUTPUT_SHAPE)
    print(
        f"✅ YOLOv8n model ready at {os.path.join(TRITON_MODELS_DIR, YOLO_MODEL_NAME)}")

    # Copy CLIP ONNX and create Triton repo
    shutil.copy(CLIP_MODEL_PATH, CLIP_ONNX_PATH)
    create_triton_repo(CLIP_MODEL_NAME, CLIP_ONNX_PATH, "input",
                       CLIP_INPUT_SHAPE, "embeddings", CLIP_OUTPUT_SHAPE)
    print(
        f"✅ CLIP model ready at {os.path.join(TRITON_MODELS_DIR, CLIP_MODEL_NAME)}")

    print("🎉 Triton model preparation completed successfully!")


if __name__ == "__main__":
    main()
