import os
import shutil
from ultralytics import YOLO

TRITON_MODELS_DIR = "triton_models"

# Example: YOLOv8n export and config
YOLO_MODEL_PATH = "yolov8n.pt"  # You must provide this file
YOLO_MODEL_NAME = "yolo"
YOLO_INPUT_SHAPE = [3, 640, 640]
YOLO_OUTPUT_SHAPE = [25200, 85]  # Adjust if your ONNX export differs

# Example: CLIP export and config (assume ONNX already available)
CLIP_MODEL_PATH = "clip-vit-b-16.onnx"  # You must provide/export this file
CLIP_MODEL_NAME = "clip"
CLIP_INPUT_SHAPE = [3, 224, 224]
CLIP_OUTPUT_SHAPE = [512]


def export_yolo_to_onnx(model_path, export_dir, imgsz=640):
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
    # Export YOLOv8n to ONNX and create Triton repo
    print("Exporting YOLOv8n to ONNX and creating Triton repo...")
    yolo_onnx_path = export_yolo_to_onnx(
        YOLO_MODEL_PATH, os.path.join(TRITON_MODELS_DIR, YOLO_MODEL_NAME, "1"))
    create_triton_repo(YOLO_MODEL_NAME, yolo_onnx_path, "images",
                       YOLO_INPUT_SHAPE, "output0", YOLO_OUTPUT_SHAPE)
    print(
        f"YOLOv8n model ready at {os.path.join(TRITON_MODELS_DIR, YOLO_MODEL_NAME)}")

    # Assume CLIP ONNX is already exported
    print("Copying CLIP ONNX and creating Triton repo...")
    clip_onnx_dest = os.path.join(
        TRITON_MODELS_DIR, CLIP_MODEL_NAME, "1", "model.onnx")
    os.makedirs(os.path.dirname(clip_onnx_dest), exist_ok=True)
    shutil.copy(CLIP_MODEL_PATH, clip_onnx_dest)
    create_triton_repo(CLIP_MODEL_NAME, clip_onnx_dest, "input",
                       CLIP_INPUT_SHAPE, "embeddings", CLIP_OUTPUT_SHAPE)
    print(
        f"CLIP model ready at {os.path.join(TRITON_MODELS_DIR, CLIP_MODEL_NAME)}")


if __name__ == "__main__":
    main()
