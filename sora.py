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
import json
from celery.result import AsyncResult
from urllib.parse import urlparse

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from flask_login import (
    UserMixin,
    login_user,
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)


from extensions import db, migrate   # <-- import from extensions

JOBS = {}  # job_id -> {"status": "queued|processing|completed|failed", "video_url": None, "message": "", "script": "", "error": None}
JOBS_LOCK = Lock()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "secret-key-change-me")
CORS(app)  # Enable CORS for frontend access

limiter = Limiter(get_remote_address, app=app, default_limits=["60/minute"])

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'   # swap to Postgres later
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
migrate.init_app(app, db)


login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)


from models import User, Persona, Script, Video, Image, Project, Project_images  # noqa: E402,F4


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

#  -----------------------------------------------------------------------------
@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@limiter.limit("30/minute")
@app.route('/api/save-img', methods=['POST'])
@login_required
def save_img():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        print("received image file")

        image_file = request.files['image']
        
        if image_file.filename == '':
            return jsonify({'error': 'No image file selected'}), 400
        
        if not allowed_file(image_file.filename):
            return jsonify({'error': 'Invalid file type. Allowed types: png, jpg, jpeg, webp'}), 400
        
        # print("valid file types")

        filename = secure_filename(image_file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        image_file.save(image_path)
        
        # print("saved image")
        
        # image_data_url= image_path_to_data_url(image_path)
        public_url = url_for('serve_upload', filename=unique_filename, _external=True)
        
        # Create DB row
        img = Image(
            user_id = current_user.id,
            url = public_url,
            path = image_path
        )
        
        try:
            db.session.add(img)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            # Clean up the file if you want
            # os.remove(image_path)
            return jsonify({'error': str(e)}), 500

        # Return the handle you’ll reuse later
        return jsonify({
            'success': True,
            'image_id': img.id,
            'url': img.url
        }), 201
        

    except Exception as e:
        return jsonify({
            'started': False,
            'error': str(e)
        }), 500

@app.route('/api/add-project-img', methods=['POST'])
@login_required        
def add_img_to_project():
    try:
        if 'image_id' not in request.form:
            return jsonify({'error': 'No image_id provided'}), 400
        print("received image_id")
        
        if 'project_id' not in request.form:
            return jsonify({'error': 'No project_id provided'}), 400
        print("received project_id")
        
        image_id = request.form['image_id']
        project_id = request.form['project_id']
        
        project_image_row = Project_images(
            project_id = project_id,
            image_id = image_id
        )
        db.session.add(project_image_row)
        db.session.commit()  # get project_image_row.id
        
        return jsonify({
            "success": True,
            "project_id": project_image_row.project_id,
            "image_id": project_image_row.image_id
        }), 202
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
@app.route('/api/project', methods=['POST'])
@login_required
def project():
    try:
        if 'name' not in request.form:
            return jsonify({'error': 'No project name provided'}), 400
        print("received project name")
        
        if 'description' not in request.form:
            return jsonify({'error': 'No product description provided'}), 400
        print("received description")
        
        name = request.form['name']
        description = request.form['description']
        
        project_row = Project(
            user_id = current_user.id,
            name = name,
            description = description
        )
        
        db.session.add(project_row)
        db.session.commit()  # get project_row.id
        
        return jsonify({
            "success": True,
            "project_id": project_row.id,
            "user_id": project_row.user_id,
            "description": project_row.description
        }), 202
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
@limiter.limit("10/minute")
@app.route('/api/persona', methods=['POST'])
@login_required
def persona(): 
    try: 
        # data = request.form if request.form else request.get_json(force=True, silent=True) or {}

        if 'description' not in request.form:
            return jsonify({'error': 'No product description provided'}), 400
        print("received description")
        
        if 'product_name' not in request.form:
            return jsonify({'error': 'No product name provided'}), 400
        print("received product name")
        
        if 'person_description' not in request.form:
            return jsonify({'error': 'No person description provided'}), 400
        print("received person description")
        
        if 'image_id' not in request.form:
            return jsonify({'error': 'No image_id provided'}), 400
        print("received image_id")
        
        # if 'user_id' not in request.form:
        #     return jsonify({'error': 'No user_id provided'}), 400
        # print("received user_id")
        
        if 'project_id' not in request.form: # user_id findable through project_id
            return jsonify({'error': 'No project_id provided'}), 400
        print("received project_id")
        
        # Required fields
        description = request.form['description']
        product_name = request.form['product_name']
        person_desc = request.form['person_description']
        image_id = request.form["image_id"]
        # user_id = request.form["user_id"]
        project_id = request.form["project_id"]
        
        if not product_name or not description or not person_desc:
            return jsonify({'error': 'product_name and description are required'}), 400
        
        # Resolve image URL: prefer image_id lookup, else accept image_url directly
        img = Image.query.get(image_id)
        if not img:
            return jsonify({'error': 'Image not found'}), 404
        
        # Quick validation of URL
        # try:
        #     _ = urlparse(img.url)
        # except Exception:
        #     return jsonify({'error': 'Invalid image_url'}), 400
        
        persona_row = Persona(
            # user_id      = user_id,
            product_name = product_name,
            description  = description,
            image_id    = image_id,
            project_id  = project_id,
            persona_json = {},                 # will fill when job completes
            status       = "processing"        # or "queued"
        )
        db.session.add(persona_row)
        db.session.commit()  # get persona_row.id
        
        prompt = generate_persona_prompt(product_name, description, person_desc)
        
        # turn into data URL for OpenAI (works from localhost)
        print(img.path)
        image_data_url = image_path_to_data_url(img.path)  # <-- This is the slow part
        
        job_id, job_status = enqueue_chatGPT_background(
            prompt=prompt,
            image_url=image_data_url,
            verbosity="high",
            effort="high"
        )

        # Save the OpenAI job id on the Persona
        persona_row.openai_job_id = job_id
        persona_row.status = "queued" if job_status == "queued" else "processing"
        db.session.commit()

        return jsonify({
            "success": True,
            "persona_id": persona_row.id,
            "project_id": persona_row.project_id,
            "openai_job_id": job_id,
            "status": persona_row.status
        }), 202
        
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

        
@limiter.limit("60/minute")
@app.route('/api/persona/<persona_id>/status', methods=['GET'])
@login_required
def persona_status(persona_id):
    persona = Persona.query.get_or_404(persona_id)

    # If already done or failed, return immediately from DB
    if persona.status in ("completed", "failed"):
        return jsonify({
            "status": persona.status,
            "persona": persona.persona_txt
        }), 200

    # If no job started yet
    if not persona.openai_job_id:
        return jsonify({
            "status": persona.status,
            "message": "No OpenAI job assigned yet."
        }), 200

    try:
        # Poll OpenAI to check if the job has completed
        resp = client.responses.retrieve(persona.openai_job_id)
        persona.status = resp.status  # "queued" | "in_progress" | "completed" | "failed"

        # If it's done, extract the output
        if resp.status == "completed":
            output = getattr(resp, "output_text", "").strip()
            try:
                persona.persona_json = json.loads(output)
                persona.persona_txt = json.loads(output).get("raw", "")
            except Exception:
                persona.persona_json = {"raw": output}
                persona.persona_txt = output
            persona.status = "completed"
            db.session.commit()

        elif resp.status == "failed":
            persona.status = "failed"
            db.session.commit()

    except Exception as e:
        # Network/API error — don't crash, just return current DB state
        print(f"Error retrieving job {persona.openai_job_id}: {e}")

    # Final response to frontend
    return jsonify({
        "status": persona.status,
        "persona": persona.persona_json if persona.status == "completed" else None
    }), 200

@limiter.limit("10/minute")
@app.route('/api/script', methods=['POST'])
@login_required
def script(): 
    try: 
        if 'persona_id' not in request.form:
            return jsonify({'error': 'No persona_id provided'}), 400
        print("received persona_id")
        
        if 'tone' not in request.form:
            return jsonify({'error': 'No tone provided'}), 400
        print("received tone")
        
        persona_id = request.form['persona_id']
        tone = request.form['tone']
        
        persona = Persona.query.get(persona_id)
        if not persona:
            return jsonify({'error': 'Persona not found'}), 404
        
        img = Image.query.get(persona.image_id)
        if not img:
            return jsonify({'error': 'Image not found'}), 404
        
        script_row = Script(
            persona_id  = persona.id,
            project_id = persona.project_id,
            tone        = tone,
            status      = "processing",        # or "queued"
            script_txt = ""
        )
        db.session.add(script_row)
        db.session.commit()  # get script_row.id
        
        prompt = generate_ad_script_prompt(persona.product_name, persona.description, persona.persona_txt, tone)
        
        image_data_url = image_path_to_data_url(img.path)  # <-- This is the slow part
        
        job_id, job_status = enqueue_chatGPT_background(
            prompt=prompt,
            image_url=image_data_url
        )
        
        script_row.openai_job_id = job_id
        script_row.status = "queued" if job_status == "queued" else "processing"
        db.session.commit()
        
        return jsonify({
            "success": True,
            "script_id": script_row.id,
            "openai_job_id": job_id,
            "status": script_row.status
        }), 202
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
     
@limiter.limit("60/minute")   
@app.route('/api/script/<script_id>/status', methods=['GET'])
@login_required
def script_status(script_id):
    s = Script.query.get_or_404(script_id)

    # If already done or failed, return immediately from DB
    if s.status in ("completed", "failed"):
        return jsonify({
            "status": s.status,
            "script": s.script_txt
        }), 200

    # If no job started yet
    if not s.openai_job_id:
        return jsonify({
            "status": s.status,
            "message": "No OpenAI job assigned yet."
        }), 200

    try:
        # Poll OpenAI to check if the job has completed
        resp = client.responses.retrieve(s.openai_job_id)
        s.status = resp.status  # "queued" | "in_progress" | "completed" | "failed"

        # If it's done, extract the output
        if resp.status == "completed":
            output = getattr(resp, "output_text", "").strip()
            try:
                s.script_json = json.loads(output)
                s.script_txt = json.loads(output).get("raw", "")
            except Exception:
                s.script_json = {"raw": output}
                s.script_txt = output
            s.status = "completed"
            db.session.commit()

        elif resp.status == "failed":
            s.status = "failed"
            db.session.commit()

    except Exception as e:
        # Network/API error — don't crash, just return current DB state
        print(f"Error retrieving job {s.openai_job_id}: {e}")

    # Final response to frontend
    return jsonify({
        "status": s.status,
        "script": s.script_json if s.status == "completed" else None
    }), 200

@limiter.limit("10/minute")
@app.route('/api/video', methods=['POST'])
@login_required
def video(): 
    try:
        if 'script_id' not in request.form:
            return jsonify({'error': 'No script_id provided'}), 400
        
        script_id = request.form['script_id']
        
        script = Script.query.get(script_id)

        p = Persona.query.get_or_404(script.persona_id)
        img = Image.query.get(p.image_id)
        
        video_row = Video(
            script_id = script.id,
            status = "processing",
            project_id = script.project_id
        )
        db.session.add(video_row)
        db.session.commit()  # get video_row.id
        
        prompt = script.script_txt
        
        job_id, job_status = enqueue_sora_background(prompt, img.path)
        
        video_row.openai_job_id = job_id
        video_row.status = "queued" if job_status == "queued" else "processing"
        db.session.commit()
        
        return jsonify({
            "success": True,
            "video_id": video_row.id,
            "openai_job_id": job_id,
            "status": video_row.status
        }), 202
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
@limiter.limit("60/minute")       
@app.route('/api/video/<video_id>/status', methods=['GET'])
@login_required
def video_status(video_id):
    
    v = Video.query.get_or_404(video_id)
    
       # If already done or failed, return immediately from DB
    if v.status in ("completed", "failed"):
        return jsonify({
            "status": v.status,
            "video_url": v.video_url
        }), 200

    # If no job started yet
    if not v.openai_job_id:
        return jsonify({
            "status": v.status,
            "message": "No OpenAI job assigned yet."
        }), 200
        
    try:
        # Poll OpenAI to check if the job has completed
        print(v.openai_job_id)
        resp = client.videos.retrieve(v.openai_job_id)
        v.status = resp.status  # "queued" | "in_progress" | "completed" | "failed"

        
        # If it's done, extract the output
        if resp.status == "completed":
            content = client.videos.download_content(v.openai_job_id)
            
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
            
            video_filename = f"{uuid.uuid4()}.mp4"
            video_path = os.path.join(app.config['VIDEO_FOLDER'], video_filename)
            with open(video_path, 'wb') as f:
                f.write(raw)
                
            video_url = url_for('serve_video', filename=video_filename, _external=True)
            
            v.file_path = video_path
            v.video_url = video_url
            v.status = "completed"
            db.session.commit()

        elif resp.status == "failed":
            v.status = "failed"
            db.session.commit()

    except Exception as e:
        # Network/API error — don't crash, just return current DB state
        print(f"Error retrieving job {v.openai_job_id}: {e}")
        
    # Final response to frontend
    return jsonify({
        "status": v.status,
        "video_url": video_url if v.status == "completed" else None
    }), 200
    

def enqueue_chatGPT_background(prompt: str, image_url: str, verbosity="medium", effort="medium"):
    """
    Runs a GPT-5 Vision request in background mode and returns (job_id, status).
    """
    resp = client.responses.create(
        model="gpt-5",
        input=[{
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": image_url, "detail": "auto"},
                {"type": "input_text",  "text": prompt}
            ]
        }],
        text={"verbosity": verbosity},
        reasoning={"effort": effort},
        background=True,
        store=True
    )
    return resp.id, getattr(resp, "status", "queued")

def enqueue_sora_background(prompt, image_path):
    
    with open(image_path, 'rb') as image_file:
        response = client.videos.create(
            model="sora-2",
            prompt=prompt,
            input_reference=image_file,
            seconds="12",
            size="720x1280",
            # background=True,
            # store=True
        )
    return response.id, getattr(response, "status", "queued")

# Login
# ------------------------------------------------------------------------------

@app.route("/auth/dev-login", methods=["POST"])
def dev_login():
    try:
        # Validate input (same pattern as your script/persona endpoints)
        if 'email' not in request.form:
            return jsonify({'error': 'No email provided'}), 400

        email = request.form['email'].strip()
        if not email:
            return jsonify({'error': 'Email cannot be empty'}), 400

        # Find or create user
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                email=email,
                credits=20,         # starter credits - change later
            )
            db.session.add(user)
            db.session.commit()

        # Log in user (Flask-Login)
        login_user(user)

        # Response consistent with your API style
        return jsonify({
            'success': True,
            'user_id': user.id,
            'email': user.email,
            'credits': user.credits
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
@app.route("/auth/logout", methods=["POST"])
@login_required
def logout():
    try:
        logout_user()  # clears the session cookie
        return jsonify({"success": True, "message": "Logged out"}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/me", methods=["GET"])
@login_required
def me():
    return jsonify({
        "success": True,
        "id": current_user.id,
        "email": current_user.email,
        "credits": current_user.credits,
    }), 200


# FUNCTIONS
# ==============================================================================

##OLD - NOT USED ANYMORE
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
        
        # video_data = generate_video_with_image(image_path, ad_script)  # reuses your polling logic
        # try:
        #     os.remove(image_path)
        # except Exception:
        #     pass
        
        # _update_job(job_id, status="processing", message="Saving video...")
        # video_filename = f"{uuid.uuid4()}.mp4"
        # video_path = os.path.join(app.config['VIDEO_FOLDER'], video_filename)
        # with open(video_path, 'wb') as f:
        #     f.write(video_data)

        # video_url = url_for('serve_video', filename=video_filename, _external=True)
        
        video_url = "video generation commented out for testing"
        time.sleep(20)
        
        _update_job(job_id, status="completed", video_url=video_url, message="Video generated successfully")
    except Exception as e:
        _update_job(job_id, status="failed", error=str(e), message="Video generation failed")

##OLD - NOT USED ANYMORE
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

##OLD - NOT USED ANYMORE
def chatGPT(prompt, image_data_url, verbosity="medium", effort="medium"): #BLOCKING
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


##OLD - NOT USED ANYMORE
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
    
    