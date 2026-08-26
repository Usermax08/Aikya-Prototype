import os
import sqlite3
import math
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- APP SETUP ---
app = FastAPI(title="AIKYA PWD Portal & Telemetry Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Detect paths relative to this backend file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
WEB_DIR = os.path.join(PROJECT_ROOT, "web")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Point to your primary SQLite DB
DB_PATH = os.path.join(BASE_DIR, "potholes.db")
if not os.path.exists(DB_PATH):
    # Fallback if aikya.db is used
    alt_db = os.path.join(BASE_DIR, "aikya.db")
    if os.path.exists(alt_db):
        DB_PATH = alt_db

ADMIN_SECRET_KEY = "aikya_admin_2026"

# --- DATABASE INITIALIZATION ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS potholes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            severity TEXT DEFAULT 'medium',
            hit_count INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            description TEXT,
            photo_path TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- PYDANTIC SCHEMAS ---
class TelemetryPayload(BaseModel):
    device_id: str
    lat: float
    lng: float
    speed_kmh: float
    z_raw: List[float]

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class StatusUpdateRequest(BaseModel):
    pothole_id: int
    status: str

class ChatMessage(BaseModel):
    message: str

# --- HELPER FUNCTIONS ---
def haversine_meters(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# --- CORE API ROUTES ---

@app.get("/api/potholes")
def get_potholes():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, lat, lng, severity, hit_count, status, last_seen FROM potholes")
    rows = cursor.fetchall()
    conn.close()

    potholes = []
    for r in rows:
        potholes.append({
            "id": r[0],
            "lat": r[1],
            "lng": r[2],
            "severity": r[3],
            "hit_count": r[4],
            "status": r[5],
            "last_seen": r[6]
        })
    return potholes

@app.post("/api/telemetry")
def process_telemetry(data: TelemetryPayload):
    # Shock threshold check (dynamic spike >= 11.8 m/s²)
    max_z = max(data.z_raw) if data.z_raw else 0.0
    is_spike = max_z >= 11.8

    if not is_spike:
        return {"status": "ignored", "is_spike": False}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Spatial clustering (5m radius)
    cursor.execute("SELECT id, lat, lng, hit_count FROM potholes WHERE status != 'resolved'")
    active_potholes = cursor.fetchall()

    matched_id = None
    for p_id, p_lat, p_lng, hits in active_potholes:
        dist = haversine_meters(data.lat, data.lng, p_lat, p_lng)
        if dist <= 5.0:
            matched_id = p_id
            new_hits = hits + 1
            new_severity = "high" if new_hits >= 8 else ("medium" if new_hits >= 4 else "low")
            cursor.execute(
                "UPDATE potholes SET hit_count = ?, severity = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
                (new_hits, new_severity, matched_id)
            )
            break

    if not matched_id:
        cursor.execute(
            "INSERT INTO potholes (lat, lng, severity, hit_count, status) VALUES (?, ?, ?, ?, ?)",
            (data.lat, data.lng, "low", 1, "active")
        )
        matched_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {"status": "logged", "is_spike": True, "pothole_id": matched_id}

@app.post("/api/report")
async def citizen_report(
    lat: float = Form(...),
    lng: float = Form(...),
    description: Optional[str] = Form("Citizen logged pothole"),
    photo: Optional[UploadFile] = File(None)
):
    saved_filename = None
    if photo:
        saved_filename = f"{int(datetime.utcnow().timestamp())}_{photo.filename}"
        file_path = os.path.join(UPLOADS_DIR, saved_filename)
        with open(file_path, "wb") as f:
            f.write(await photo.read())

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reports (lat, lng, description, photo_path) VALUES (?, ?, ?, ?)",
        (lat, lng, description, saved_filename)
    )
    # Also create/update pothole ticket
    cursor.execute(
        "INSERT INTO potholes (lat, lng, severity, hit_count, status) VALUES (?, ?, ?, ?, ?)",
        (lat, lng, "medium", 3, "active")
    )
    conn.commit()
    conn.close()

    return {"success": True, "message": "Grievance recorded successfully."}

# --- SECURE ADMIN & RBAC ROUTES ---

@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest):
    if req.username == "admin" and req.password == "pwd@aikya2026":
        return {"success": True, "token": ADMIN_SECRET_KEY}
    raise HTTPException(status_code=401, detail="Invalid admin credentials.")

@app.patch("/api/potholes/status")
def update_pothole_status(req: StatusUpdateRequest, authorization: Optional[str] = Header(None)):
    if authorization != f"Bearer {ADMIN_SECRET_KEY}":
        raise HTTPException(status_code=403, detail="Unauthorized: Admin access required.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE potholes SET status = ? WHERE id = ?", (req.status, req.pothole_id))
    conn.commit()
    conn.close()

    return {"success": True, "pothole_id": req.pothole_id, "new_status": req.status}

# --- AI MUNICIPAL ASSISTANT ROUTE ---

@app.post("/api/chat")
async def municipal_ai_chat(req: ChatMessage):
    msg = req.message.lower()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM potholes WHERE status = 'active'")
    active_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM potholes WHERE status = 'resolved'")
    resolved_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM potholes WHERE severity = 'high' AND status = 'active'")
    high_count = cursor.fetchone()[0]
    conn.close()

    if "active" in msg or "count" in msg or "how many" in msg:
        reply = f"Currently, there are **{active_count} active potholes** detected across the sector ({high_count} classified as High Risk). **{resolved_count}** have been auto-verified as resolved."
    elif "material" in msg or "asphalt" in msg or "budget" in msg:
        est_bags = (high_count * 2.5) + ((active_count - high_count) * 1.0)
        reply = f"Based on current active hazards, estimated asphalt requisition is **{est_bags:.1f} bags** of bituminous cold mix with **{active_count}L** of emulsion tack coat."
    elif "speed" in msg or "bump" in msg or "filter" in msg:
        reply = "AIKYA uses dual-phase directional analysis: Speed bumps produce an initial **upward acceleration (+Z)**, which our 50Hz band-pass filter isolates and drops. Potholes produce a sudden **free-fall drop (-Z)** followed by a kinetic shock."
    else:
        reply = f"AIKYA Monitoring Node is online. Managing {active_count} active road defects. How can I assist with work orders or field manifests today?"

    return {"reply": reply}

# --- FRONTEND HTML ROUTES ---

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    return FileResponse(os.path.join(WEB_DIR, "dashboard.html"))

@app.get("/sensor", response_class=HTMLResponse)
def get_sensor_node():
    return FileResponse(os.path.join(WEB_DIR, "sensor.html"))

@app.get("/report", response_class=HTMLResponse)
def get_report_portal():
    return FileResponse(os.path.join(WEB_DIR, "report.html"))

@app.get("/admin", response_class=HTMLResponse)
def get_admin_page():
    return FileResponse(os.path.join(WEB_DIR, "admin.html"))