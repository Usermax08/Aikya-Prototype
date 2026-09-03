import os
import sqlite3
import math
import random
import time
import json
import urllib.request
import urllib.error
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

# Point to primary SQLite DB
DB_PATH = os.path.join(BASE_DIR, "potholes.db")
if not os.path.exists(DB_PATH):
    alt_db = os.path.join(BASE_DIR, "aikya.db")
    if os.path.exists(alt_db):
        DB_PATH = alt_db

ADMIN_SECRET_KEY = "aikya_admin_2026"

# --- RESEND HTTPS EMAIL 2FA CONFIGURATION ---
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ADMIN_TARGET_EMAIL = "dtheekshanritwik@gmail.com"

# In-memory OTP storage: {"username": {"otp": "123456", "expires": timestamp}}
OTP_STORE = {}

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

class VerifyOtpRequest(BaseModel):
    username: str
    otp: str

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

def send_resend_email_otp(target_email: str, otp_code: str):
    """Sends OTP via Resend REST HTTPS API with verbose diagnostic error logging."""
    if not RESEND_API_KEY:
        print("[Resend Warning] RESEND_API_KEY environment variable is missing.")
        return

    url = "https://api.resend.com/emails"
    
    html_content = f"""
    <div style="font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 24px; border-radius: 12px; max-width: 480px;">
        <h2 style="color: #38bdf8; margin-top: 0;">AIKYA Command Gate</h2>
        <p style="color: #94a3b8; font-size: 14px;">An administrative sign-in was attempted for the PWD road defect console.</p>
        <div style="background: #1e293b; padding: 16px; border-radius: 8px; text-align: center; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #38bdf8; font-family: monospace;">{otp_code}</span>
        </div>
        <p style="color: #94a3b8; font-size: 12px; margin-bottom: 0;">This passcode is valid for 5 minutes. If this was not you, review server access logs immediately.</p>
    </div>
    """
    
    payload = {
        "from": "AIKYA Security <onboarding@resend.dev>",
        "to": [target_email],
        "subject": f"🚨 AIKYA Municipal 2FA Code: {otp_code}",
        "html": html_content
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[Resend Email Dispatched] Status: {resp.status}")
    except urllib.error.HTTPError as e:
        error_details = e.read().decode("utf-8")
        print(f"[Resend Dispatch Warning] HTTP {e.code} Error: {error_details}")
    except Exception as e:
        print(f"[Resend Dispatch Warning] Could not send via Resend: {e}")

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
    max_z = max(data.z_raw) if data.z_raw else 0.0
    is_spike = max_z >= 11.8

    if not is_spike:
        return {"status": "ignored", "is_spike": False}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

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
    cursor.execute(
        "INSERT INTO potholes (lat, lng, severity, hit_count, status) VALUES (?, ?, ?, ?, ?)",
        (lat, lng, "medium", 3, "active")
    )
    conn.commit()
    conn.close()

    return {"success": True, "message": "Grievance recorded successfully."}

# --- SECURE ADMIN 2FA ROUTES ---

@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest):
    if req.username != "admin" or req.password != "pwd@aikya2026":
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")

    # Generate 6-digit random OTP
    otp = f"{random.randint(100000, 999999)}"
    OTP_STORE[req.username] = {
        "otp": otp,
        "expires": time.time() + 300  # Valid for 5 minutes
    }

    # Dispatch via Resend HTTPS API
    send_resend_email_otp(ADMIN_TARGET_EMAIL, otp)

    # Server console fallback log (always visible in Render live logs)
    print("\n" + "=" * 46)
    print("✉️  [AIKYA RESEND 2FA DISPATCHED]")
    print(f"Target Inbox:  {ADMIN_TARGET_EMAIL}")
    print(f"6-Digit OTP:   {otp}")
    print("=" * 46 + "\n")

    return {
        "success": True,
        "otp_required": True,
        "message": "6-digit verification code sent to registered authority inbox."
    }

@app.post("/api/admin/verify-otp")
def verify_admin_otp(req: VerifyOtpRequest):
    record = OTP_STORE.get(req.username)
    if not record:
        raise HTTPException(status_code=400, detail="No OTP pending. Please submit credentials again.")

    if time.time() > record["expires"]:
        OTP_STORE.pop(req.username, None)
        raise HTTPException(status_code=400, detail="OTP expired. Please request a new code.")

    if req.otp.strip() != record["otp"]:
        raise HTTPException(status_code=401, detail="Incorrect OTP verification code.")

    OTP_STORE.pop(req.username, None)
    return {"success": True, "token": ADMIN_SECRET_KEY}

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