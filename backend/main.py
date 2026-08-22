from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import datetime

from models import SessionLocal, init_db, Hit, Pothole
from filters import detect_spike
from cluster import cluster_hits, haversine_distance

init_db()

app = FastAPI(title="AIKYA Pothole Detection API")

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
    lat: float
    lng: float
    z_accel: float
    speed_kmh: Optional[float] = 20.0
    device_id: Optional[str] = "phone_1"
    raw_window: Optional[List[float]] = None
    is_simulated_bump: Optional[bool] = False
    is_smooth_pass: Optional[bool] = False

@app.get("/")
def read_root():
    return {"status": "online", "system": "AIKYA Road Defect Tracking"}

@app.post("/api/telemetry")
def ingest_telemetry(payload: TelemetryPayload, db=Depends(get_db)):
    if payload.is_smooth_pass:
        potholes = db.query(Pothole).filter(Pothole.status != "resolved").all()
        resolved_count = 0
        for p in potholes:
            dist = haversine_distance(payload.lat, payload.lng, p.lat, p.lng)
            if dist <= 12.0:
                p.status = "resolved"
                resolved_count += 1
        db.commit()
        return {"status": "smooth_pass_logged", "resolved_potholes": resolved_count}

    window = payload.raw_window if payload.raw_window else [payload.z_accel]
    is_spike = payload.is_simulated_bump or detect_spike(window)

    if is_spike:
        new_hit = Hit(
            device_id=payload.device_id,
            lat=payload.lat,
            lng=payload.lng,
            z_accel=payload.z_accel,
            speed_kmh=payload.speed_kmh,
            is_spike=True
        )
        db.add(new_hit)
        db.commit()

        all_hits = db.query(Hit).filter(Hit.is_spike == True).all()
        hit_dicts = [{"lat": h.lat, "lng": h.lng, "z_accel": h.z_accel} for h in all_hits]
        
        clusters = cluster_hits(hit_dicts, eps_meters=10.0, min_samples=3)
        
        for cl in clusters:
            existing = None
            for p in db.query(Pothole).all():
                if haversine_distance(cl['lat'], cl['lng'], p.lat, p.lng) < 10.0:
                    existing = p
                    break
            
            if existing:
                existing.hit_count = cl['hit_count']
                existing.severity = cl['severity']
                existing.last_seen = datetime.datetime.utcnow()
            else:
                db.add(Pothole(
                    lat=cl['lat'],
                    lng=cl['lng'],
                    hit_count=cl['hit_count'],
                    severity=cl['severity'],
                    status="verified"
                ))
        db.commit()
        return {"status": "spike_recorded", "clustered": len(clusters)}

    return {"status": "normal_reading_ignored"}

@app.get("/api/potholes")
def get_potholes(db=Depends(get_db)):
    potholes = db.query(Pothole).all()
    return [{
        "id": p.id,
        "lat": p.lat,
        "lng": p.lng,
        "hit_count": p.hit_count,
        "severity": p.severity,
        "status": p.status,
        "last_seen": p.last_seen.isoformat()
    } for p in potholes]

@app.get("/api/hits")
def get_hits(db=Depends(get_db)):
    hits = db.query(Hit).order_by(Hit.id.desc()).limit(50).all()
    return [{
        "id": h.id,
        "lat": h.lat,
        "lng": h.lng,
        "z_accel": h.z_accel,
        "timestamp": h.timestamp.isoformat()
    } for h in hits]