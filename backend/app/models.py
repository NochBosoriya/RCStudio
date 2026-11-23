from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text, JSON, DateTime, MetaData, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
from .config import settings

metadata = MetaData()
Base = declarative_base(metadata=metadata)

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class MediaAsset(Base):
    __tablename__ = "media_assets"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    file_path = Column(String)
    asset_metadata = Column(JSON)

class DownloadJob(Base):
    __tablename__ = "download_jobs"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    url = Column(String)
    status = Column(String)
    progress = Column(Float, default=0.0)

class TranscriptLine(Base):
    __tablename__ = "transcript_lines"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    source_text = Column(Text)
    display_text = Column(Text)
    tts_segments = Column(JSON)
    start_time = Column(Float)
    end_time = Column(Float)
    character_id = Column(Integer)
    duration_fit_status = Column(String)

class CharacterProfile(Base):
    __tablename__ = "character_profiles"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String)
    gender = Column(String)
    age_group = Column(String)
    role = Column(String)
    voice_engine = Column(String)
    voice_id = Column(String)
    pitch = Column(Float, default=0.0)
    speed = Column(Float, default=1.0)

class EpisodeGlossary(Base):
    __tablename__ = "episode_glossary"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    source_term = Column(String)
    policy = Column(String) # TRANSLATE | KEEP_ORIGINAL | ROMANIZE_EN
    display_name = Column(String)
    tts_phonetic_km = Column(String)

class ExportJob(Base):
    __tablename__ = "export_jobs"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    output_path = Column(String)
    status = Column(String)
    progress = Column(Float, default=0.0)

class PublishJob(Base):
    __tablename__ = "publish_jobs"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    platform = Column(String)
    status = Column(String)
    scheduled_at = Column(DateTime, nullable=True)

engine = create_engine(settings.DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
