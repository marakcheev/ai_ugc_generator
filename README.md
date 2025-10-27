# AI UGC Video Generator

A Flask backend that uses OpenAI's Sora API to generate videos from product images and descriptions.

## Features

- Upload product images and descriptions
- Generate AI videos using Sora-2
- REST API with CORS support
- Automatic video hosting and URL generation

## Setup

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Set your OpenAI API key:**
```bash
export OPENAI_API_KEY='your-api-key-here'
```

3. **Run the server:**
```bash
python sora.py
```

The server will start on `http://localhost:5000`

## API Endpoints

### Generate Video
**POST** `/api/generate-video`

Generates a video from an image and product description.

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body:
  - `image` (file): Product image (png, jpg, jpeg, gif, webp)
  - `description` (text): Product description/prompt

**Response:**
```json
{
  "success": true,
  "video_url": "http://localhost:5000/videos/uuid.mp4",
  "message": "Video generated successfully"
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Error message"
}
```

### Health Check
**GET** `/api/health`

Check if the server is running.

**Response:**
```json
{
  "status": "healthy"
}
```

### Serve Video
**GET** `/videos/<filename>`

Serves generated video files.

## Example Usage

### Using cURL:
```bash
curl -X POST http://localhost:5000/api/generate-video \
  -F "image=@/path/to/product.jpg" \
  -F "description=A sleek smartphone floating in a futuristic environment with neon lights"
```

### Using JavaScript (Fetch API):
```javascript
const formData = new FormData();
formData.append('image', imageFile);
formData.append('description', 'Your product description here');

fetch('http://localhost:5000/api/generate-video', {
  method: 'POST',
  body: formData
})
.then(response => response.json())
.then(data => {
  console.log('Video URL:', data.video_url);
})
.catch(error => console.error('Error:', error));
```

## Configuration

- **Max file size:** 16MB
- **Allowed image formats:** png, jpg, jpeg, gif, webp
- **Video duration:** 4 seconds
- **Video size:** 720x1280 (portrait)
- **Model:** Sora-2

## Directory Structure

```
ai_ugc_generator/
├── sora.py              # Main Flask application
├── requirements.txt     # Python dependencies
├── uploads/            # Temporary image uploads (auto-created)
├── videos/             # Generated videos (auto-created)
└── example.html        # Example frontend
```

## Notes

- Videos are generated asynchronously and may take some time
- The API polls OpenAI's servers every 10 seconds for completion status
- Uploaded images are deleted after video generation
- Generated videos are stored permanently (consider implementing cleanup)

## Production Deployment

For production use, consider:
1. Using a production WSGI server (e.g., Gunicorn)
2. Implementing video file cleanup or cloud storage
3. Adding authentication/rate limiting
4. Using environment variables for configuration
5. Implementing proper error logging

