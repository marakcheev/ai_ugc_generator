from datetime import datetime
from uuid import uuid4
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.sqlite import JSON as SqliteJSON
from sqlalchemy import Index, UniqueConstraint

from extensions import db   # <-- import from extensions, NOT sora

def gen_id():
    return str(uuid4())

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    email = db.Column(db.String, unique=True, nullable=True)   # add google auth later
    credits = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    personas = db.relationship("Persona", backref="user", lazy=True)
    
    images = db.relationship("Image", backref="user", lazy=True, cascade="all,delete")


class Image(db.Model):
    __tablename__ = "images"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)

    url = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_images_user_created", "user_id", "created_at"),
    )

class Persona(db.Model):
    __tablename__ = "personas"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)

    product_name = db.Column(db.String, nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String, nullable=False)
    persona_json = db.Column(SqliteJSON, nullable=False)       # store the GPT persona dict
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String, nullable=False, default="processing")     # queued | processing | completed | failed
    openai_job_id = db.Column(db.String, index=True)
    
    scripts = db.relationship("Script", backref="persona", lazy=True, cascade="all,delete")

    __table_args__ = (
        Index("ix_personas_user_created", "user_id", "created_at"),
    )

class Script(db.Model):
    __tablename__ = "scripts"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    persona_id = db.Column(db.String, db.ForeignKey("personas.id"), nullable=False)

    script_text = db.Column(db.Text, nullable=False)
    tone = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String, nullable=False, default="processing")     # queued | processing | completed | failed

    
    videos = db.relationship("Video", backref="script", lazy=True, cascade="all,delete")

    __table_args__ = (
        Index("ix_scripts_persona_created", "persona_id", "created_at"),
    )

class Video(db.Model):
    __tablename__ = "videos"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    script_id = db.Column(db.String, db.ForeignKey("scripts.id"), nullable=False)

    status = db.Column(db.String, nullable=False, default="queued")  # queued|processing|completed|failed
    file_path = db.Column(db.String, nullable=True)                   # local path or S3 key
    video_url = db.Column(db.String, nullable=True)                   # public URL if serving via HTTP
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        Index("ix_videos_status_created", "status", "created_at"),
    )