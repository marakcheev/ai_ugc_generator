from openai import OpenAI
import time
import os
import sys

# Initialize client with API key from environment variable
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("Please set the OPENAI_API_KEY environment variable")
client = OpenAI(api_key=api_key)

with open(image_path := "sample_720p.jpeg", "rb") as img_file:
    response = client.videos.create(
        model="sora-2",
        prompt="A cool cat riding a motorcycle through a neon city at night",
        seconds="4",
        size="720x1280",
        input_reference=img_file
    )
    

print(response)

video_id = response.id

while True:
    video_status = client.videos.retrieve(video_id)
    
    if video_status.status == "completed":
        print("Video generation completed!")
        break
    elif video_status.status == "failed":
        print("Video generation failed!")
        raise Exception("Video generation failed")
    time.sleep(10)
    
# The SDK may return a streaming/response wrapper (HttpxBinaryResponseContent).
# Ensure we convert it to raw bytes before writing to disk.
content = client.videos.download_content(video_id)

# Try several ways to extract bytes safely.
if hasattr(content, "read") and callable(content.read):
    try:
        raw = content.read()
    except TypeError:
        # Some streaming objects may require calling without arguments
        raw = content.read
elif hasattr(content, "content"):
    raw = content.content
elif isinstance(content, (bytes, bytearray)):
    raw = content
else:
    # Fallback: attempt to coerce to bytes
    raw = bytes(content)

with open("video.mp4", "wb") as f:
    f.write(raw)

# Quick verification
try:
    size = os.path.getsize("video.mp4")
    print(f"Saved video.mp4 ({size} bytes)")
    if size == 0:
        print("Warning: file size is 0 bytes — download may have failed or returned empty content")
except Exception as e:
    print("Could not verify file size:", e)