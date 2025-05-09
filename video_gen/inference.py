import torch
from diffusers import StableVideoDiffusionPipeline
from diffusers.utils import export_to_video
from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import StreamingResponse
import io
import logging
import os
import tempfile
import ollama

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load LLaVA-NeXT-Video-7B via Ollama
def load_model():
    model = ollama.load("llava-next-video-7b-dpo")
    return model

model = load_model()

@app.post("/generate")
async def generate_video(prompt: str = Form(...), num_frames: int = Form(25)):
    try:
        logger.info(f"Generating video for prompt: {prompt}")
        # Generate initial frame using LLaVA-NeXT-Video
        initial_frame = model.generate(prompt, format="image")
        
        # Use Stable Video Diffusion for frame interpolation
        pipe = StableVideoDiffusionPipeline.from_pretrained(
            "stabilityai/stable-video-diffusion-img2vid",
            torch_dtype=torch.float16,
            variant="fp16"
        )
        pipe = pipe.to("cuda")
        pipe.enable_model_cpu_offload()

        video_frames = pipe(
            prompt=prompt,
            image=initial_frame,
            num_frames=num_frames,
            num_inference_steps=25,
            guidance_scale=7.5,
            height=320,
            width=576,
            generator=torch.Generator(device="cuda").manual_seed(42)
        ).frames[0]

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
            export_to_video(video_frames, temp_file.name, fps=7)
            with open(temp_file.name, 'rb') as f:
                video_content = f.read()
            os.unlink(temp_file.name)

        return StreamingResponse(
            io.BytesIO(video_content),
            media_type="video/mp4",
            headers={"Content-Disposition": "attachment; filename=generated_video.mp4"}
        )

    except Exception as e:
        logger.error(f"Error generating video: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
