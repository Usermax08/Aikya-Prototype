import numpy as np
from sklearn.cluster import DBSCAN
import math

EARTH_RADIUS_METERS = 6371000.0

def haversine_distance(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(a))

def cluster_hits(hits, eps_meters=10.0, min_samples=3):
    if len(hits) < min_samples:
        return []

    coords = np.array([[h['lat'], h['lng']] for h in hits])
    coords_rad = np.radians(coords)
    eps_rad = eps_meters / EARTH_RADIUS_METERS

    db = DBSCAN(eps=eps_rad, min_samples=min_samples, metric='haversine')
    labels = db.fit_predict(coords_rad)

    clusters = []
    unique_labels = set(labels) - {-1}

    for label in unique_labels:
        cluster_points = [hits[i] for i in range(len(hits)) if labels[i] == label]
        mean_lat = float(np.mean([p['lat'] for p in cluster_points]))
        mean_lng = float(np.mean([p['lng'] for p in cluster_points]))
        max_accel = max([p['z_accel'] for p in cluster_points])
        
        severity = "low"
        if max_accel > 18.0 or len(cluster_points) >= 6:
            severity = "high"
        elif max_accel > 13.0 or len(cluster_points) >= 3:
            severity = "medium"

        clusters.append({
            "lat": round(mean_lat, 6),
            "lng": round(mean_lng, 6),
            "hit_count": len(cluster_points),
            "severity": severity,
            "status": "verified"
        })

    return clusters