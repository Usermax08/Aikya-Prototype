import os
import sys
import datetime
import random

# Ensure root and backend directories are in Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from models import SessionLocal, init_db, Pothole, Hit
except ImportError:
    from backend.models import SessionLocal, init_db, Pothole, Hit

def seed_demo_data():
    init_db()
    db = SessionLocal()

    # Clear existing entries
    db.query(Hit).delete()
    db.query(Pothole).delete()
    db.commit()

    # SRMIST Kattankulathur Campus coordinates
    base_lat, base_lng = 12.8231, 80.0451

    campus_defects = [
        {"offset": (0.0008, 0.0012), "hits": 14, "severity": "high", "status": "verified"},
        {"offset": (-0.0012, 0.0018), "hits": 8, "severity": "medium", "status": "verified"},
        {"offset": (0.0019, -0.0009), "hits": 4, "severity": "low", "status": "verified"},
        {"offset": (-0.0021, -0.0015), "hits": 18, "severity": "high", "status": "verified"},
        {"offset": (0.0005, -0.0022), "hits": 6, "severity": "medium", "status": "verified"},
        {"offset": (-0.0015, 0.0008), "hits": 11, "severity": "high", "status": "resolved"},
        {"offset": (0.0024, 0.0021), "hits": 5, "severity": "low", "status": "resolved"},
    ]

    now = datetime.datetime.now(datetime.timezone.utc)

    for p_data in campus_defects:
        p_lat = base_lat + p_data["offset"][0]
        p_lng = base_lng + p_data["offset"][1]

        pothole = Pothole(
            lat=p_lat,
            lng=p_lng,
            hit_count=p_data["hits"],
            severity=p_data["severity"],
            status=p_data["status"],
            first_seen=now - datetime.timedelta(hours=random.randint(4, 72)),
            last_seen=now,
            smooth_pass_count=3 if p_data["status"] == "resolved" else 0
        )
        db.add(pothole)

    db.commit()
    db.close()
    print("AIKYA SRMIST Defect clusters successfully seeded!")

if __name__ == "__main__":
    seed_demo_data()