import os
import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

try:
    from backend.models import SessionLocal, init_db, Hit, Pothole
    from backend.filters import butterworth_filter
    from backend.cluster import cluster_hits, check_smooth_pass_resolution
except ImportError:
    from models import SessionLocal, init_db, Hit, Pothole
    from filters import butterworth_filter
    from cluster import cluster_hits, check_smooth_pass_resolution

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

class TelemetryPayload(BaseModel):
    device_id: str
    lat: float
    lng: float
    speed_kmh: float
    z_raw: List[float]

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