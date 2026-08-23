import os
import sys
import datetime
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

app = FastAPI(title="AIKYA PWD Portal")

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

# Auto-seed the exact 16 defect cases
@app.on_event("startup")
def startup_seed_db():
    db = SessionLocal()
    if db.query(Pothole).count() == 0:
        fixed_time = datetime.datetime(2026, 8, 22, 20, 9, tzinfo=datetime.timezone.utc)
        
        all_defects = [
            {"id": 1, "lat": 12.81780, "lng": 80.03970, "hits": 3, "severity": "low", "status": "verified"},
            {"id": 2, "lat": 12.82857, "lng": 80.04636, "hits": 9, "severity": "high", "status": "verified"},
            {"id": 3, "lat": 12.82604, "lng": 80.04505, "hits": 8, "severity": "medium", "status": "verified"},
            {"id": 4, "lat": 12.81610, "lng": 80.03765, "hits": 12, "severity": "high", "status": "resolved"},
            {"id": 5, "lat": 12.81670, "lng": 80.05756, "hits": 8, "severity": "high", "status": "verified"},
            {"id": 6, "lat": 12.83347, "lng": 80.04039, "hits": 9, "severity": "low", "status": "resolved"},
            {"id": 7, "lat": 12.82068, "lng": 80.04930, "hits": 13, "severity": "low", "status": "verified"},
            {"id": 8, "lat": 12.80911, "lng": 80.04414, "hits": 13, "severity": "low", "status": "verified"},
            {"id": 9, "lat": 12.82644, "lng": 80.04610, "hits": 7, "severity": "high", "status": "verified"},
            {"id": 10, "lat": 12.82874, "lng": 80.04678, "hits": 10, "severity": "medium", "status": "verified"},
            {"id": 11, "lat": 12.81957, "lng": 80.05842, "hits": 8, "severity": "medium", "status": "verified"},
            {"id": 12, "lat": 12.81997, "lng": 80.05242, "hits": 8, "severity": "medium", "status": "verified"},
            {"id": 13, "lat": 12.81265, "lng": 80.03511, "hits": 6, "severity": "low", "status": "resolved"},
            {"id": 14, "lat": 12.81186, "lng": 80.04293, "hits": 3, "severity": "high", "status": "verified"},
            {"id": 15, "lat": 12.82136, "lng": 80.03556, "hits": 12, "severity": "medium", "status": "resolved"},
            {"id": 16, "lat": 12.81010, "lng": 80.05510, "hits": 7, "severity": "high", "status": "verified"},
        ]

        for p_data in all_defects:
            pothole = Pothole(
                id=p_data["id"],
                lat=p_data["lat"],
                lng=p_data["lng"],
                hit_count=p_data["hits"],
                severity=p_data["severity"],
                status=p_data["status"],
                first_seen=fixed_time,
                last_seen=fixed_time
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
        last_seen=now
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
            "first_seen": p.first_seen.strftime("%Y-%m-%d %H:%M") if p.first_seen else "2026-08-22 20:09",
            "last_seen": p.last_seen.strftime("%Y-%m-%d %H:%M") if p.last_seen else "2026-08-22 20:09"
        }
        for p in records
    ]

# Static Web Hosting
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