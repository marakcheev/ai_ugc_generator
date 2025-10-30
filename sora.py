from flask import Flask, request, jsonify, send_from_directory, url_for
from flask_cors import CORS
from openai import OpenAI
import time
import os
import uuid
from werkzeug.utils import secure_filename
import base64, mimetypes
from PIL import Image
import io
import re
from threading import Thread, Lock
import time

JOBS = {}  # job_id -> {"status": "queued|processing|completed|failed", "video_url": None, "message": "", "script": "", "error": None}
JOBS_LOCK = Lock()

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Configuration
UPLOAD_FOLDER = 'uploads'
VIDEO_FOLDER = 'videos'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

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



def _update_job(job_id, **kwargs):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kwargs)

def _process_video_job(job_id, image_path, image_data_url, product_name, description, person_description, tone):
    try:
        
        _update_job(job_id, status="processing", message="Generating persona...")
        persona_prompt = generate_persona_prompt(product_name, description, person_description)
        gpt_response = chatGPT(persona_prompt, image_data_url, verbosity="high", effort="high")
        persona = getattr(gpt_response, "output_text", "")
        print("Persona Created")
        
        _update_job(job_id, status="processing", message="Generating script...")
        ad_script_prompt = generate_ad_script_prompt(product_name, description, persona, tone)#the prompt that generates the ad script.
        gpt_response1 = chatGPT(ad_script_prompt, image_data_url)
        ad_script = getattr(gpt_response1, "output_text", "")
        print("Final Sora Prompt Created")
        
        _update_job(job_id, status="processing", message="Generating video with Sora...")
        
        video_data = generate_video_with_image(image_path, ad_script)  # reuses your polling logic
        try:
            os.remove(image_path)
        except Exception:
            pass
        
        _update_job(job_id, status="processing", message="Saving video...")
        video_filename = f"{uuid.uuid4()}.mp4"
        video_path = os.path.join(app.config['VIDEO_FOLDER'], video_filename)
        with open(video_path, 'wb') as f:
            f.write(video_data)

        video_url = url_for('serve_video', filename=video_filename, _external=True)
        # video_url = "video generation commented out for testing"
        time.sleep(20)
        
        _update_job(job_id, status="completed", video_url=video_url, message="Video generated successfully")
    except Exception as e:
        _update_job(job_id, status="failed", error=str(e), message="Video generation failed")



def generate_video_with_image(image_path, prompt):
    """Generate video using Sora API with image and description"""
    
    # return None
    # Open and upload the image to OpenAI
    with open(image_path, 'rb') as image_file:
        # Create video with image input
        response = client.videos.create(
            model="sora-2",
            prompt=prompt,
            input_reference=image_file,
            seconds="12",
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

def chatGPT(prompt, image_data_url, verbosity="medium", effort="medium"):
    response = client.responses.create(
        model="gpt-5",
        input=[
            {
                "role": "user",
                "content": [
                { "type": "input_image", "image_url": image_data_url, "detail": "auto" },
                { "type": "input_text",  "text": prompt }
                ]
            }
        ],
        text={"verbosity": verbosity },
        reasoning={ "effort": effort },
    )
    return response
    # return None

def generate_persona_prompt(name, description, person_description):
    """
    Load persona_prompt.txt (next to this file), replace placeholders and return the result.
    Replaces exact tokens: {PRODUCT NAME} and {PRODUCT DESCRIPTION}.
    """
    path = os.path.join(os.path.dirname(__file__), "persona_prompt.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            template = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Required template file not found at: {path}")
    # Ensure inputs are strings and perform replacements
    name_str = "" if name is None else str(name)
    desc_str = "" if description is None else str(description)
    
    prompt = template.replace("{PRODUCT NAME}", name_str).replace("{PRODUCT DESCRIPTION}", desc_str).replace("{PERSON DESCRIPTION}", person_description)
    
    print("Persona Prompt Created")
    return prompt

def generate_ad_script_prompt(name, description, persona, tone):
    """
    Load ad_script_prompt.txt (next to this file), replace placeholders and return the result.
    Replaces exact tokens: {PERSONA}, {PRODUCT NAME} and {PRODUCT DESCRIPTION}.
    """
    path = os.path.join(os.path.dirname(__file__), "ad_script_prompt.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            template = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Required template file not found at: {path}")

    # Ensure inputs are strings and perform replacements
    name_str = "" if name is None else str(name)
    desc_str = "" if description is None else str(description)
    persona_str = "" if persona is None else str(persona)

    prompt = (
        template
        .replace("{PERSONA}", persona_str)
        .replace("{PRODUCT NAME}", name_str)
        .replace("{PRODUCT DESCRIPTION}", desc_str)
        .replace("{TONE}", tone)
    )

    print("AD Script Prompt Created")
    return prompt

def parse_scripts(gpt_output: str) -> list[str]:
    """
    Extracts scripts labeled like:
      SCRIPT 1: ...
      SCRIPT 2: ...
      SCRIPT 3: ...
    Returns a list of 3 strings (or fewer if parsing fails).
    """
    pattern = r"SCRIPT\s*(\d+)\s*:\s*(.*?)(?=SCRIPT\s*\d+\s*:|$)"
    blocks = re.findall(pattern, gpt_output, flags=re.I | re.S)
    # Sort by the captured number, then take only the text
    blocks_sorted = [text.strip() for num, text in sorted(blocks, key=lambda x: int(x[0]))]
    return blocks_sorted


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
        print("received image file")
        
        if 'description' not in request.form:
            return jsonify({'error': 'No product description provided'}), 400
        print("received description")
        
        if 'product_name' not in request.form:
            return jsonify({'error': 'No product name provided'}), 400
        print("received product name")
        
        if 'person_description' not in request.form:
            return jsonify({'error': 'No person description provided'}), 400
        print("received person description")
        
        if 'tone' not in request.form:
            return jsonify({'error': 'No tone provided'}), 400
        print("received tone")
        
        image_file = request.files['image']
        description = request.form['description']
        product_name = request.form['product_name']
        person_description = request.form['person_description']
        tone = request.form['tone']
        
        if image_file.filename == '':
            return jsonify({'error': 'No image file selected'}), 400
        
        if not allowed_file(image_file.filename):
            return jsonify({'error': 'Invalid file type. Allowed types: png, jpg, jpeg, webp'}), 400
        
        print("valid file types")

        # Save uploaded image
        filename = secure_filename(image_file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        image_file.save(image_path)
        
        print("saved image")
        
        image_data_url= image_path_to_data_url(image_path)
        print("converted image to data url")
        


        # persona_prompt = generate_persona_prompt(product_name, description, person_description)
        # gpt_response = chatGPT(persona_prompt, image_data_url, verbosity="high", effort="high")
        # persona = getattr(gpt_response, "output_text", "")
        # print("Persona Created")
        
        # ad_script_prompt = generate_ad_script_prompt(product_name, description, persona, tone)#the prompt that generates the ad script.
        # gpt_response1 = chatGPT(ad_script_prompt, image_data_url)
        # ad_script = getattr(gpt_response1, "output_text", "")
        # print("Final Sora Prompt Created") #makes 3 scripts in 1. need user to pick one before generating.

        # ad_script = "Product rotates in a 3D space with upbeat music in the background. Sparkly effects appear around the product to highlight its features."
        
        

        # Generate video
        # print("Generating video with Sora...")
        # video_data = generate_video_with_image(image_path, ad_script)
        # os.remove(image_path)
        
        # print("Saving video...")

        # # # Save video with unique filename
        # video_filename = f"{uuid.uuid4()}.mp4"
        # video_path = os.path.join(app.config['VIDEO_FOLDER'], video_filename)
        
        # with open(video_path, 'wb') as f:
        #     f.write(video_data)
        
        # # Generate video URL
        # video_url = url_for('serve_video', filename=video_filename, _external=True)
        # # video_url = "no video generated"
        
        # return jsonify({
        #     'success': True,
        #     'video_url': video_url,
        #     'script': ad_script,
        #     'message': 'Video generated successfully'
        # }), 200
        
        # --- NEW: queue a background job and return job_id immediately ---
        job_id = str(uuid.uuid4())
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "queued",
                "video_url": None,
                "message": "Job queued",
                # "script": ad_script,
                "error": None,
            }

        # Launch background worker
        t = Thread(target=_process_video_job, args=(job_id, image_path, image_data_url, product_name, description, person_description, tone), daemon=True)
        t.start()

        # Respond fast (no long post)
        return jsonify({
            "started": True,
            "job_id": job_id,
            # "script": ad_script
        }), 202
        
    except Exception as e:
        return jsonify({
            'started': False,
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

@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({'home': 'we out here'}), 200

@app.route('/api/job/<job_id>', methods=['GET'])
def job_status(job_id):
    with JOBS_LOCK:
        data = JOBS.get(job_id)

    if not data:
        return jsonify({"success": False, "error": "Unknown job_id"}), 404

    # When completed, the same call returns the video_url
    return jsonify({
        "success": True,
        "job_id": job_id,
        "status": data["status"],          # queued | processing | completed | failed
        "message": data.get("message"),
        "video_url": data.get("video_url"),
        "error": data.get("error"),
    }), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)