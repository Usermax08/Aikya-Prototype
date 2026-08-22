import datetime
import random
from sqlalchemy.orm import Session

try:
    from backend.models import SessionLocal, init_db, Pothole, Hit
except ImportError:
    from models import SessionLocal, init_db, Pothole, Hit

def seed_demo_data():
    init_db()
    db: Session = SessionLocal()

    # Clear existing data for fresh demo
    db.query(Hit).delete()
    db.query(Pothole).delete()
    db.commit()

    base_lat, base_lng = 12.8231, 80.0451  # Kattankulathur Sector

    demo_potholes = [
        {"offset": (0.0012, 0.0015), "hits": 14, "severity": "high", "status": "verified"},
        {"offset": (-0.0018, 0.0022), "hits": 8, "severity": "medium", "status": "verified"},
        {"offset": (0.0025, -0.0011), "hits": 4, "severity": "low", "status": "verified"},
        {"offset": (-0.0031, -0.0020), "hits": 19, "severity": "high", "status": "verified"},
        {"offset": (0.0008, -0.0034), "hits": 6, "severity": "medium", "status": "verified"},
        {"offset": (-0.0022, 0.0011), "hits": 11, "severity": "high", "status": "resolved"},
        {"offset": (0.0034, 0.0028), "hits": 5, "severity": "low", "status": "resolved"},
    ]

    for p_data in demo_potholes:
        p_lat = base_lat + p_data["offset"][0]
        p_lng = base_lng + p_data["offset"][1]

        pothole = Pothole(
            lat=p_lat,
            lng=p_lng,
            hit_count=p_data["hits"],
            severity=p_data["severity"],
            status=p_data["status"],
            first_seen=datetime.datetime.utcnow() - datetime.timedelta(hours=random.randint(4, 72)),
            last_seen=datetime.datetime.utcnow(),
            smooth_pass_count=3 if p_data["status"] == "resolved" else 0
        )
        db.add(pothole)

    db.commit()
    db.close()
    print("AIKYA Database successfully seeded with demo defects.")

if __name__ == "__main__":
    seed_demo_data()