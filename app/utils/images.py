import base64, mimetypes

def image_path_to_data_url(image_path: str) -> str:
    # Convert unsupported input (like WEBP) to JPEG for GPT-5
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    if mime == "image/webp":
        img = Image.open(image_path).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        raw = buf.read()
        mime = "image/jpeg"
    else:
        with open(image_path, "rb") as f:
            raw = f.read()
    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime};base64,{b64}"