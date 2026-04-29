import requests
import math
import hashlib
import json
from django.core.cache import cache

ORS_BASE_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

class RoutePoint:
    def __init__(self, lat, lon, cumulative_miles):
        self.lat = lat
        self.lon = lon
        self.cumulative_miles = cumulative_miles

def haversine_miles(lat1, lon1, lat2, lon2):
    """Fast approximate distance in miles using Haversine formula."""
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))

def get_route(start_coords, end_coords, api_key):
    """
    Makes ONE API call to get full route polyline.
    start_coords: [lon, lat]  <- ORS uses lon,lat order
    end_coords: [lon, lat]
    Returns list of RoutePoint objects with mile markers
    """
    cache_key = "ors_route_" + hashlib.md5(json.dumps([start_coords, end_coords]).encode()).hexdigest()
    cached_data = cache.get(cache_key)
    
    if cached_data:
        data = cached_data
    else:
        headers = {"Authorization": api_key}
        body = {
            "coordinates": [start_coords, end_coords],
            "radiuses": [-1, -1],
            "units": "mi"
        }
        try:
            response = requests.post(ORS_BASE_URL, json=body, headers=headers, timeout=5)
            if response.status_code != 200:
                raise Exception(f"ORS non-200: {response.status_code}")
            data = response.json()
        except Exception as e:
            print(f"DEBUG: Primary ORS API failed ({e}), falling back to OSRM...")
            # Fallback to OSRM Public API
            osrm_url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[0]},{start_coords[1]};{end_coords[0]},{end_coords[1]}?overview=full&geometries=geojson"
            osrm_res = requests.get(osrm_url, timeout=10)
            if osrm_res.status_code != 200:
                raise Exception(f"Both Primary and Fallback APIs failed. OSRM Error: {osrm_res.text}")
            
            osrm_data = osrm_res.json()['routes'][0]
            osrm_coords = osrm_data['geometry']['coordinates']
            osrm_duration = osrm_data.get('duration', 0)  # seconds
            data = {"features": [{"geometry": {"coordinates": osrm_coords}}], "_duration": osrm_duration}
            
        cache.set(cache_key, data, timeout=86400) # Cache for 24 hours
    # Extract duration
    try:
        # ORS format
        duration_seconds = data['features'][0]['properties']['summary']['duration']
    except (KeyError, TypeError, IndexError):
        try:
            duration_seconds = data.get('_duration', 0)
        except Exception:
            duration_seconds = 0

    coordinates = data['features'][0]['geometry']['coordinates']

    route_points = []
    cumulative_miles = 0.0

    # Optimization: If we have too many points, the distance calculation
    # and JSON serialization become very slow. 
    # For a cross-country route, every 10th point is still very smooth.
    # But we MUST calculate cumulative miles correctly across all points.
    
    for i, coord in enumerate(coordinates):
        lon, lat = coord[0], coord[1]

        if i > 0:
            prev_lon, prev_lat = coordinates[i - 1][0], coordinates[i - 1][1]
            # Use Haversine for speed (50x faster than geopy.geodesic)
            dist = haversine_miles(prev_lat, prev_lon, lat, lon)
            cumulative_miles += dist

        route_points.append(RoutePoint(lat, lon, cumulative_miles))

    # To keep response size manageable for long routes, we sub-sample the returned polyline
    # but we KEEP the full route_points for the station filtering algorithm accuracy.
    # Use consistent 3000-point sampling for better route detail and accuracy
    if len(coordinates) > 3000:
        stride = len(coordinates) // 3000
        sampled_polyline = coordinates[::stride]
    else:
        sampled_polyline = coordinates

    return route_points, sampled_polyline, int(duration_seconds)

def get_multi_stop_route(coords_list, api_key):
    """
    Makes a routing call with multiple waypoints to get the true polyline 
    including exact turn-by-turn detours to the fuel stations.
    coords_list: list of [lon, lat] points
    Returns the raw GeoJSON coordinates array (in [lon, lat] format).
    """
    cache_key = "ors_multi_" + hashlib.md5(json.dumps(coords_list).encode()).hexdigest()
    cached_coords = cache.get(cache_key)
    
    if cached_coords:
        return cached_coords['coords'], cached_coords['duration']

    headers = {"Authorization": api_key}
    body = {
        "coordinates": coords_list,
        "radiuses": [-1] * len(coords_list),
        "units": "mi"
    }
    
    duration = 0
    try:
        response = requests.post(ORS_BASE_URL, json=body, headers=headers, timeout=5)
        if response.status_code != 200:
            raise Exception("ORS returned non-200")
        resp_data = response.json()
        coords = resp_data['features'][0]['geometry']['coordinates']
        duration = resp_data['features'][0]['properties']['summary']['duration']
    except Exception as e:
        print(f"DEBUG: ORS multi-stop failed ({e}), falling back to OSRM...")
        try:
            coords_str = ';'.join([f"{c[0]},{c[1]}" for c in coords_list])
            osrm_url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"
            osrm_res = requests.get(osrm_url, timeout=10)
            if osrm_res.status_code != 200:
                return None, 0
            osrm_data = osrm_res.json()['routes'][0]
            coords = osrm_data['geometry']['coordinates']
            duration = osrm_data.get('duration', 0)
        except Exception as e2:
            print(f"DEBUG: OSRM Fallback failed: {e2}")
            return None, 0
    
    # Use consistent 3000-point sampling for better route detail and accuracy
    if len(coords) > 3000:
        stride = len(coords) // 3000
        coords = coords[::stride]
        
    cache.set(cache_key, {'coords': coords, 'duration': duration}, timeout=86400)
    return coords, int(duration)
