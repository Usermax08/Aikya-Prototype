import datetime
from sqlalchemy import Column, Integer, Float, String, DateTime, Boolean, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./aikya.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Hit(Base):
    __tablename__ = "hits"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, default="dev_default")
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    z_accel = Column(Float, nullable=False)
    speed_kmh = Column(Float, default=0.0)
    is_spike = Column(Boolean, default=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class Pothole(Base):
    __tablename__ = "potholes"

    id = Column(Integer, primary_key=True, index=True)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    hit_count = Column(Integer, default=1)
    severity = Column(String, default="medium")
    status = Column(String, default="new")
    first_seen = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)