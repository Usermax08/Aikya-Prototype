import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy.orm import Session
from datetime import datetime

try:
    from backend.models import Hit, Pothole
except ImportError:
    from models import Hit, Pothole

def haversine_distance(lat1, lon1, lat2, lon2):
    r = 6371.0088
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2.0)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return r * c

def cluster_hits(db: Session):
    recent_hits = db.query(Hit).filter(Hit.is_spike == True).all()
    if len(recent_hits) < 3:
        return

    coords = np.array([[h.lat, h.lng] for h in recent_hits])
    
    # 10 meters in radians
    kms_per_radian = 6371.0088
    epsilon = (10.0 / 1000.0) / kms_per_radian
    
    dbscan = DBSCAN(eps=epsilon, min_samples=3, metric='haversine')
    dbscan.fit(np.radians(coords))
    
    labels = dbscan.labels_
    unique_labels = set(labels)

    for k in unique_labels:
        if k == -1:
            continue
        
        class_member_mask = (labels == k)
        cluster_points = coords[class_member_mask]
        cluster_hits_records = [recent_hits[i] for i, val in enumerate(class_member_mask) if val]

        unique_devices = set(h.device_id for h in cluster_hits_records)
        if len(unique_devices) < 2:
            continue

        centroid_lat = float(np.mean(cluster_points[:, 0]))
        centroid_lng = float(np.mean(cluster_points[:, 1]))
        hit_count = len(cluster_hits_records)

        max_accel = max(h.z_accel for h in cluster_hits_records)
        severity = "low"
        if max_accel > 20.0 or hit_count >= 8:
            severity = "high"
        elif max_accel > 15.0 or hit_count >= 4:
            severity = "medium"

        existing = None
        for p in db.query(Pothole).filter(Pothole.status == "verified").all():
            dist_km = haversine_distance(centroid_lat, centroid_lng, p.lat, p.lng)
            if dist_km <= 0.015:  # within 15 meters
                existing = p
                break

        if existing:
            existing.lat = (existing.lat + centroid_lat) / 2.0
            existing.lng = (existing.lng + centroid_lng) / 2.0
            existing.hit_count = max(existing.hit_count, hit_count)
            existing.severity = severity
            existing.last_seen = datetime.utcnow()
        else:
            new_pothole = Pothole(
                lat=centroid_lat,
                lng=centroid_lng,
                hit_count=hit_count,
                severity=severity,
                status="verified",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                smooth_pass_count=0
            )
            db.add(new_pothole)

    db.commit()

def check_smooth_pass_resolution(db: Session, pass_lat: float, pass_lng: float):
    active_potholes = db.query(Pothole).filter(Pothole.status == "verified").all()
    for p in active_potholes:
        dist_km = haversine_distance(pass_lat, pass_lng, p.lat, p.lng)
        if dist_km <= 0.015:
            p.smooth_pass_count += 1
            if p.smooth_pass_count >= 3:
                p.status = "resolved"
                p.last_seen = datetime.utcnow()
    db.commit()