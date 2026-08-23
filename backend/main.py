import os
import sys
import datetime
import random
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

try:
    from models import SessionLocal, init_db, Hit, Pothole
    from filters import butterworth_filter
    from cluster import cluster_hits, check_smooth_pass_resolution
except ImportError:
    from backend.models import SessionLocal, init_db, Hit, Pothole
    from backend.filters import butterworth_filter
    from backend.cluster import cluster_hits, check_smooth_pass_resolution

init_db()

app = FastAPI(title="AIKYA PWD Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Auto-seed the 16 defect cases on startup
@app.on_event("startup")
def startup_seed_db():
    db = SessionLocal()
    if db.query(Pothole).count() == 0:
        base_lat, base_lng = 12.8231, 80.0451
        now = datetime.datetime.now(datetime.timezone.utc)

        all_defects = [
            {"offset": (0.0008, 0.0012), "hits": 24, "severity": "high", "status": "verified"},
            {"offset": (-0.0012, 0.0018), "hits": 12, "severity": "medium", "status": "verified"},
            {"offset": (0.0019, -0.0009), "hits": 6, "severity": "low", "status": "verified"},
            {"offset": (-0.0021, -0.0015), "hits": 31, "severity": "high", "status": "verified"},
            {"offset": (0.0005, -0.0022), "hits": 9, "severity": "medium", "status": "verified"},
            {"offset": (-0.0015, 0.0008), "hits": 19, "severity": "high", "status": "resolved"},
            {"offset": (0.0024, 0.0021), "hits": 7, "severity": "low", "status": "resolved"},
            {"offset": (-0.0003, 0.0027), "hits": 16, "severity": "high", "status": "verified"},
            {"offset": (0.0015, 0.0005), "hits": 10, "severity": "medium", "status": "verified"},
            {"offset": (-0.0028, 0.0019), "hits": 22, "severity": "high", "status": "verified"},
            {"offset": (0.0031, -0.0024), "hits": 5, "severity": "low", "status": "verified"},
            {"offset": (-0.0009, -0.0031), "hits": 14, "severity": "medium", "status": "verified"},
            {"offset": (0.0020, 0.0035), "hits": 28, "severity": "high", "status": "verified"},
            {"offset": (-0.0035, -0.0008), "hits": 15, "severity": "high", "status": "resolved"},
            {"offset": (0.0002, 0.0019), "hits": 8, "severity": "medium", "status": "resolved"},
            {"offset": (-0.0018, -0.0025), "hits": 4, "severity": "low", "status": "resolved"},
        ]

        for p_data in all_defects:
            p_lat = base_lat + p_data["offset"][0]
            p_lng = base_lng + p_data["offset"][1]
            pothole = Pothole(
                lat=p_lat,
                lng=p_lng,
                hit_count=p_data["hits"],
                severity=p_data["severity"],
                status=p_data["status"],
                first_seen=now - datetime.timedelta(hours=random.randint(4, 96)),
                last_seen=now,
                smooth_pass_count=3 if p_data["status"] == "resolved" else 0
            )
            db.add(pothole)
        db.commit()
    db.close()

class TelemetryPayload(BaseModel):
    device_id: str
    lat: float
    lng: float
    speed_kmh: float
    z_raw: List[float]

class CitizenReportPayload(BaseModel):
    lat: float
    lng: float
    severity: str = "medium"
    description: Optional[str] = "Citizen reported defect"
    photo_base64: Optional[str] = None

@app.post("/api/telemetry")
async def receive_telemetry(payload: TelemetryPayload, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    cutoff_freq = 5.0
    sampling_rate = 50.0
    filtered_accel = butterworth_filter(payload.z_raw, cutoff_freq, sampling_rate)
    
    max_vertical_spike = max(map(abs, filtered_accel)) if len(filtered_accel) > 0 else 0.0
    is_impact = max_vertical_spike > 12.0
    
    hit = Hit(
        device_id=payload.device_id,
        lat=payload.lat,
        lng=payload.lng,
        z_accel=round(float(max_vertical_spike), 2),
        speed_kmh=round(float(payload.speed_kmh), 1),
        is_spike=is_impact
    )
    db.add(hit)
    db.commit()

    if is_impact:
        background_tasks.add_task(cluster_hits, db)
    else:
        background_tasks.add_task(check_smooth_pass_resolution, db, payload.lat, payload.lng)

    return {
        "status": "processed",
        "is_spike": is_impact,
        "max_z_accel": round(float(max_vertical_spike), 2)
    }

@app.post("/api/report")
def create_citizen_report(payload: CitizenReportPayload, db: Session = Depends(get_db)):
    now = datetime.datetime.now(datetime.timezone.utc)
    new_pothole = Pothole(
        lat=payload.lat,
        lng=payload.lng,
        hit_count=1,
        severity=payload.severity.lower(),
        status="verified",
        first_seen=now,
        last_seen=now,
        smooth_pass_count=0
    )
    db.add(new_pothole)
    db.commit()
    db.refresh(new_pothole)
    return {
        "status": "success",
        "id": new_pothole.id,
        "has_photo": bool(payload.photo_base64),
        "message": f"Defect logged as Ticket #{new_pothole.id}."
    }

@app.get("/api/potholes")
def get_potholes(db: Session = Depends(get_db)):
    records = db.query(Pothole).all()
    return [
        {
            "id": p.id,
            "lat": p.lat,
            "lng": p.lng,
            "hit_count": p.hit_count,
            "severity": p.severity,
            "status": p.status,
            "first_seen": p.first_seen.isoformat() if p.first_seen else None,
            "last_seen": p.last_seen.isoformat() if p.last_seen else None
        }
        for p in records
    ]

# Serve Static Web Frontend Pages
web_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(os.path.join(web_dir, "dashboard.html"))

    @app.get("/sensor")
    def serve_sensor():
        return FileResponse(os.path.join(web_dir, "sensor.html"))

    @app.get("/report")
    def serve_report():
        return FileResponse(os.path.join(web_dir, "report.html"))