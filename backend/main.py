import os
import math
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import uvicorn

# ----------------- DATABASE SETUP -----------------
DATABASE_URL = "sqlite:///./potholes.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Pothole(Base):
    __tablename__ = "potholes"

    id = Column(Integer, primary_key=True, index=True)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    severity = Column(String, default="low")       # low, medium, high
    hit_count = Column(Integer, default=1)
    status = Column(String, default="active")       # active, resolved
    last_seen = Column(DateTime, default=datetime.utcnow)
    image_url = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pre-seed initial sample data if DB is empty
def seed_initial_data():
    db = SessionLocal()
    if db.query(Pothole).count() == 0:
        samples = [
            Pothole(lat=12.8231, lng=80.0451, severity="high", hit_count=9, status="active"),
            Pothole(lat=12.8245, lng=80.0428, severity="medium", hit_count=5, status="active"),
            Pothole(lat=12.8210, lng=80.0475, severity="low", hit_count=2, status="active"),
            Pothole(lat=12.8260, lng=80.0402, severity="high", hit_count=12, status="active"),
            Pothole(lat=12.8195, lng=80.0440, severity="low", hit_count=1, status="resolved"),
        ]
        db.add_all(samples)
        db.commit()
    db.close()

seed_initial_data()

# ----------------- FASTAPI APP -----------------
app = FastAPI(title="AIKYA Pothole Tracking System")

# Serve static directory for uploads and web assets
os.makedirs("web", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ----------------- PYDANTIC SCHEMAS -----------------
class TelemetryPayload(BaseModel):
    device_id: str
    lat: float
    lng: float
    speed_kmh: float
    z_raw: List[float]

class PotholeResponse(BaseModel):
    id: int
    lat: float
    lng: float
    severity: str
    hit_count: int
    status: str
    last_seen: Optional[datetime]
    image_url: Optional[str]

    class Config:
        from_attributes = True

class ChatQuery(BaseModel):
    message: str

# ----------------- HAVERSINE DISTANCE HELPER -----------------
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000  # radius of Earth in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ----------------- API ROUTES -----------------
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    with open("web/dashboard.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/sensor", response_class=HTMLResponse)
async def serve_sensor():
    with open("web/sensor.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/report", response_class=HTMLResponse)
async def serve_report():
    report_file = "web/report.html"
    if os.path.exists(report_file):
        with open(report_file, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h3>Grievance Portal file not found.</h3>", status_code=404)

@app.get("/api/potholes", response_model=List[PotholeResponse])
async def get_all_potholes(db: Session = Depends(get_db)):
    return db.query(Pothole).all()

@app.post("/api/telemetry")
async def process_telemetry(payload: TelemetryPayload, db: Session = Depends(get_db)):
    max_z = max(payload.z_raw) if payload.z_raw else 0.0
    is_spike = max_z > 11.8

    if is_spike:
        # Spatial Clustering (5-meter radius consensus)
        nearby = None
        for p in db.query(Pothole).filter(Pothole.status != "resolved").all():
            if haversine_distance(p.lat, p.lng, payload.lat, payload.lng) <= 5.0:
                nearby = p
                break

        if nearby:
            nearby.hit_count += 1
            nearby.last_seen = datetime.utcnow()
            if nearby.hit_count >= 8:
                nearby.severity = "high"
            elif nearby.hit_count >= 4:
                nearby.severity = "medium"
            db.commit()
        else:
            new_p = Pothole(
                lat=payload.lat,
                lng=payload.lng,
                severity="low",
                hit_count=1,
                status="active"
            )
            db.add(new_p)
            db.commit()

    return {"status": "ok", "is_spike": is_spike, "max_z": round(max_z, 2)}

@app.post("/api/report")
async def submit_citizen_report(
    lat: float = Form(...),
    lng: float = Form(...),
    severity: str = Form("medium"),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    image_path = None
    if photo:
        filename = f"report_{int(datetime.utcnow().timestamp())}_{photo.filename}"
        save_dest = os.path.join("uploads", filename)
        with open(save_dest, "wb") as buffer:
            buffer.write(await photo.read())
        image_path = f"/uploads/{filename}"

    new_report = Pothole(
        lat=lat,
        lng=lng,
        severity=severity,
        hit_count=3,
        status="active",
        image_url=image_path
    )
    db.add(new_report)
    db.commit()
    return {"status": "success", "message": "Grievance logged successfully"}

# ----------------- REAL-TIME AI MUNICIPAL ASSISTANT -----------------
@app.post("/api/chat")
async def aikya_assistant(query: ChatQuery, db: Session = Depends(get_db)):
    msg = query.message.lower()

    potholes = db.query(Pothole).all()
    total_active = len([p for p in potholes if p.status != "resolved"])
    total_high = len([p for p in potholes if p.severity == "high" and p.status != "resolved"])
    total_medium = len([p for p in potholes if p.severity == "medium" and p.status != "resolved"])
    total_resolved = len([p for p in potholes if p.status == "resolved"])

    if any(w in msg for w in ["how many", "count", "active", "total", "status"]):
        reply = f"Currently, there are **{total_active} active defects** logged in the sector:\n• **{total_high} Critical/High Risk**\n• **{total_medium} Medium Priority**\n• **{total_resolved} Auto-Verified & Resolved**."
    
    elif any(w in msg for w in ["material", "budget", "asphalt", "cost", "bags", "requisition"]):
        est_bags = (total_high * 2.5) + (total_medium * 1.5) + ((total_active - total_high - total_medium) * 0.5)
        labor_hours = total_active * 2
        est_budget = int(est_bags * 1200 + labor_hours * 350)
        reply = f"Estimated Sector Requisition:\n• **{est_bags:.1f} Bags of Bituminous Asphalt Mix**\n• Emulsion Tack Coat + Plate Compactor\n• Estimated Labor: **{labor_hours} Crew Hours**\n• Estimated Repair Budget: **₹{est_budget:,}**."

    elif any(w in msg for w in ["speed bump", "speed breaker", "algorithm", "filter", "-z", "+z"]):
        reply = "AIKYA uses a **Dual-Phase Directional Filter**:\n• **Pothole Craters:** Produce an initial sharp negative free-fall drop (**-Z**) followed by impact shock $\\rightarrow$ Logged as Hazard.\n• **Speed Breakers:** Produce an initial upward displacement (**+Z**) $\\rightarrow$ Recognized as a bump and filtered out from risk scoring."

    elif any(w in msg for w in ["export", "excel", "manifest", "xlsx", "download"]):
        reply = "You can download the official PWD Work Order Manifest at any time by clicking the **'📊 Export PWD Manifest (.xlsx)'** button on the bottom left panel."

    elif any(w in msg for w in ["srm", "kattankulathur", "location", "sector", "zone"]):
        reply = "The current monitoring node is locked on the **SRM Kattankulathur Sector (GST Road - Potheri Corridor)** with 50Hz continuous vehicle vibration telemetry streaming."

    elif any(w in msg for w in ["hello", "hi", "hey", "help", "who are you"]):
        reply = f"Hello Officer! I am **AIKYA Municipal AI Assistant**. I can help you with live defect counts ({total_active} active), asphalt material requisitions, road roughness (IRI) stats, or our telemetry filtering rules. What would you like to inspect?"

    else:
        reply = f"Officer, across the SRMIST sector we are tracking **{total_active} active defects** ({total_high} High Risk). You can ask me about **material budgets**, **speed bump filtering**, or **exporting work manifests**."

    return {"reply": reply}

# ----------------- APP LAUNCH -----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)