from flask import Flask, request, jsonify, send_from_directory, url_for
from flask_cors import CORS
from openai import OpenAI
import time
import os
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Configuration
UPLOAD_FOLDER = 'uploads'
VIDEO_FOLDER = 'videos'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Create necessary directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VIDEO_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['VIDEO_FOLDER'] = VIDEO_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize OpenAI client
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("Please set the OPENAI_API_KEY environment variable")
client = OpenAI(api_key=api_key)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_video_with_image(image_path, description):
    """Generate video using Sora API with image and description"""
    
    # Open and upload the image to OpenAI
    with open(image_path, 'rb') as image_file:
        # Create video with image input
        response = client.videos.create(
            model="sora-2",
            prompt=description,
            image=image_file,
            seconds="4",
            size="720x1280"
        )
    
    video_id = response.id
    
    # Poll for video completion
    while True:
        video_status = client.videos.retrieve(video_id)
        
        if video_status.status == "completed":
            break
        elif video_status.status == "failed":
            raise Exception("Video generation failed")
        time.sleep(10)
    
    # Download video content
    content = client.videos.download_content(video_id)
    
    # Extract bytes safely
    if hasattr(content, "read") and callable(content.read):
        try:
            raw = content.read()
        except TypeError:
            raw = content.read
    elif hasattr(content, "content"):
        raw = content.content
    elif isinstance(content, (bytes, bytearray)):
        raw = content
    else:
        raw = bytes(content)
    
    return raw


@app.route('/api/generate-video', methods=['POST'])
def generate_video():
    """
    Endpoint to generate video from image and description
    Expects: multipart/form-data with 'image' file and 'description' text
    Returns: JSON with video URL
    """
    try:
        # Validate request
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        if 'description' not in request.form:
            return jsonify({'error': 'No product description provided'}), 400
        
        image_file = request.files['image']
        description = request.form['description']
        
        if image_file.filename == '':
            return jsonify({'error': 'No image file selected'}), 400
        
        if not allowed_file(image_file.filename):
            return jsonify({'error': 'Invalid file type. Allowed types: png, jpg, jpeg, gif, webp'}), 400
        
        # Save uploaded image
        filename = secure_filename(image_file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        image_file.save(image_path)
        
        # Generate video
        video_data = generate_video_with_image(image_path, description)
        
        # Save video with unique filename
        video_filename = f"{uuid.uuid4()}.mp4"
        video_path = os.path.join(app.config['VIDEO_FOLDER'], video_filename)
        
        with open(video_path, 'wb') as f:
            f.write(video_data)
        
        # Clean up uploaded image
        os.remove(image_path)
        
        # Generate video URL
        video_url = url_for('serve_video', filename=video_filename, _external=True)
        
        return jsonify({
            'success': True,
            'video_url': video_url,
            'message': 'Video generated successfully'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/videos/<filename>')
def serve_video(filename):
    """Serve generated video files"""
    return send_from_directory(app.config['VIDEO_FOLDER'], filename)


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)