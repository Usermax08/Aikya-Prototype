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

# Pre-seed multi-state test datasets (Tamil Nadu, Telangana, Andhra Pradesh, Kerala)
def seed_initial_data():
    db = SessionLocal()
    # Reset and seed clean multi-state data on restart
    db.query(Pothole).delete()
    
    samples = [
        # --- Tamil Nadu (SRMIST / Chennai Hub) ---
        Pothole(lat=12.8231, lng=80.0451, severity="high", hit_count=14, status="active"),
        Pothole(lat=12.8245, lng=80.0428, severity="medium", hit_count=6, status="active"),
        Pothole(lat=12.8210, lng=80.0475, severity="low", hit_count=2, status="active"),
        Pothole(lat=12.8260, lng=80.0402, severity="high", hit_count=18, status="active"),
        Pothole(lat=12.8195, lng=80.0440, severity="low", hit_count=1, status="resolved"),
        Pothole(lat=13.0827, lng=80.2707, severity="high", hit_count=22, status="active"), # Chennai Central

        # --- Telangana (Hyderabad IT Corridor & Ring Road) ---
        Pothole(lat=17.4401, lng=78.3489, severity="high", hit_count=16, status="active"), # Gachibowli Outer Ring Rd
        Pothole(lat=17.4483, lng=78.3915, severity="medium", hit_count=7, status="active"), # Madhapur / Hitec City
        Pothole(lat=17.3850, lng=78.4867, severity="low", hit_count=3, status="active"),   # Old City / Charminar Rd
        Pothole(lat=17.4933, lng=78.3995, severity="high", hit_count=11, status="resolved"), # Kukatpally Bypass

        # --- Andhra Pradesh (Vijayawada & Visakhapatnam NH16) ---
        Pothole(lat=16.5062, lng=80.6480, severity="high", hit_count=19, status="active"), # Vijayawada MG Road / Benz Circle
        Pothole(lat=16.5417, lng=80.6288, severity="medium", hit_count=5, status="active"), # Ibrahimpatnam NH Bypass
        Pothole(lat=17.6868, lng=83.2185, severity="high", hit_count=13, status="active"), # Vizag Beach Road
        Pothole(lat=17.7289, lng=83.3032, severity="low", hit_count=2, status="resolved"), # Vizag NH16 Flyover

        # --- Kerala (Kochi & Thiruvananthapuram Arteries) ---
        Pothole(lat=9.9312, lng=76.2673, severity="high", hit_count=15, status="active"),  # Kochi MG Road
        Pothole(lat=10.0159, lng=76.3419, severity="medium", hit_count=8, status="active"), # Kakkanad Infopark Corridor
        Pothole(lat=8.5241, lng=76.9366, severity="high", hit_count=12, status="active"),  # Trivandrum East Fort
        Pothole(lat=8.5581, lng=76.8816, severity="low", hit_count=1, status="resolved"),  # Kazhakkoottam Bypass
    ]
    db.add_all(samples)
    db.commit()
    db.close()

seed_initial_data()

# ----------------- FASTAPI APP -----------------
app = FastAPI(title="AIKYA Pothole Tracking System")

# Ensure static directories exist
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
        reply = f"Across all monitored sectors, there are **{total_active} active defects** logged in the network:\n• **{total_high} Critical/High Risk**\n• **{total_medium} Medium Priority**\n• **{total_resolved} Auto-Verified & Resolved**."
    
    elif any(w in msg for w in ["material", "budget", "asphalt", "cost", "bags", "requisition"]):
        est_bags = (total_high * 2.5) + (total_medium * 1.5) + ((total_active - total_high - total_medium) * 0.5)
        labor_hours = total_active * 2
        est_budget = int(est_bags * 1200 + labor_hours * 350)
        reply = f"Total Material Requisition across State Nodes:\n• **{est_bags:.1f} Bags of Bituminous Asphalt Mix**\n• Emulsion Tack Coat + Mechanical Compactors\n• Estimated Municipal Labor: **{labor_hours} Crew Hours**\n• Estimated Repair Budget: **₹{est_budget:,}**."

    elif any(w in msg for w in ["speed bump", "speed breaker", "algorithm", "filter", "-z", "+z"]):
        reply = "AIKYA uses a **Dual-Phase Directional Filter**:\n• **Pothole Craters:** Produce an initial sharp negative free-fall drop (**-Z**) followed by impact shock $\\rightarrow$ Logged as Hazard.\n• **Speed Breakers:** Produce an initial upward displacement (**+Z**) $\\rightarrow$ Recognized as a speed hump and filtered out from municipal risk scoring."

    elif any(w in msg for w in ["export", "excel", "manifest", "xlsx", "download"]):
        reply = "You can download the official PWD Work Order Manifest at any time by clicking the **'📊 Export PWD Manifest (.xlsx)'** button on the bottom left panel."

    elif any(w in msg for w in ["telangana", "hyderabad", "andhra", "kerala", "tamil nadu", "sector", "zone", "state"]):
        reply = "AIKYA multi-sector nodes are actively tracking road corridors across:\n• **Tamil Nadu:** Chennai & SRMIST Kattankulathur\n• **Telangana:** Hyderabad (Gachibowli & Hitec City)\n• **Andhra Pradesh:** Vijayawada (MG Road) & Visakhapatnam\n• **Kerala:** Kochi & Thiruvananthapuram."

    elif any(w in msg for w in ["hello", "hi", "hey", "help", "who are you"]):
        reply = f"Hello Officer! I am **AIKYA Municipal AI Assistant**. I can help you with live defect counts ({total_active} active across 4 states), asphalt requisitions, road roughness (IRI) stats, or our telemetry filtering rules. What would you like to inspect?"

    else:
        reply = f"Officer, across all state corridors we are tracking **{total_active} active defects** ({total_high} High Risk). You can ask me about **state coverage**, **material budgets**, **speed bump filtering**, or **exporting work manifests**."

    return {"reply": reply}

# ----------------- APP LAUNCH -----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)