import datetime
import random
from models import SessionLocal, init_db, Hit, Pothole

init_db()
db = SessionLocal()

# Base coordinates centered around SRM Kattankulathur corridor
BASE_LAT = 12.8231
BASE_LNG = 80.0451

def seed_database():
    db.query(Hit).delete()
    db.query(Pothole).delete()
    db.commit()

    print("Populating initial realistic defect clusters...")

    severities = ["low", "medium", "high"]
    statuses = ["verified", "verified", "verified", "resolved"]

    for i in range(1, 17):
        offset_lat = (random.random() - 0.5) * 0.03
        offset_lng = (random.random() - 0.5) * 0.03
        p_lat = round(BASE_LAT + offset_lat, 6)
        p_lng = round(BASE_LNG + offset_lng, 6)
        
        hit_count = random.randint(3, 14)
        sev = random.choice(severities)
        stat = random.choice(statuses)

        pothole = Pothole(
            lat=p_lat,
            lng=p_lng,
            hit_count=hit_count,
            severity=sev,
            status=stat,
            first_seen=datetime.datetime.utcnow() - datetime.timedelta(hours=random.randint(2, 48)),
            last_seen=datetime.datetime.utcnow()
        )
        db.add(pothole)

        for _ in range(hit_count):
            jitter_lat = p_lat + (random.random() - 0.5) * 0.00003
            jitter_lng = p_lng + (random.random() - 0.5) * 0.00003
            max_accel = 14.0 if sev == "low" else (17.5 if sev == "medium" else 22.0)
            
            db.add(Hit(
                device_id=f"vehicle_{random.randint(100, 999)}",
                lat=round(jitter_lat, 6),
                lng=round(jitter_lng, 6),
                z_accel=round(max_accel + (random.random() - 0.5) * 2.0, 2),
                speed_kmh=round(random.uniform(25.0, 55.0), 1),
                is_spike=True
            ))

    db.commit()
    db.close()
    print("Database seeded with 16 verified defects and raw sensor hits!")

if __name__ == "__main__":
    seed_database()