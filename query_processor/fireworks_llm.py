import requests
import base64

FIREWORKS_API_KEY = "fw_3ZSqs56AkP32464uhbhVoHxx"
FIREWORKS_ENDPOINT = "https://api.fireworks.ai/inference/v1/chat/completions"


def query_fireworks_qwen(query_text, image_bytes=None):
    headers = {
        "Authorization": f"Bearer {FIREWORKS_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "qwen2.5-vl-7b",
        "messages": [
            {"role": "user", "content": query_text}
        ]
    }
    if image_bytes:
        # Fireworks may require base64-encoded images in the payload
        data["messages"][0]["image"] = base64.b64encode(image_bytes).decode()
    response = requests.post(FIREWORKS_ENDPOINT, headers=headers, json=data)
    response.raise_for_status()
    return response.json()
