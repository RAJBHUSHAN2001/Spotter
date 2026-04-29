import math
from bisect import bisect_left, bisect_right

class CandidateStation:
    def __init__(self, station, route_type, detour_miles, mile_marker):
        self.station = station
        self.route_type = route_type
        self.detour_miles = detour_miles
        self.mile_marker = mile_marker
        self.price = station.retail_price
        self.effective_price = station.retail_price


def haversine_miles(lat1, lon1, lat2, lon2):
    """Fast approximate distance in miles using Haversine formula."""
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def get_stations_near_route(route_points, all_stations, max_distance_miles=20):
    """
    Optimized station filtering using lat-sorted bisection.
    This reduces the search space from O(Stations * Points) to 
    O(Points * log(Stations) + Points * NearbyStations).
    """
    # 1. Sort all stations by latitude for bisection search
    # We only care about stations with coordinates
    stations_with_coords = [s for s in all_stations if s.lat is not None and s.lon is not None]
    stations_sorted = sorted(stations_with_coords, key=lambda s: s.lat)
    station_lats = [s.lat for s in stations_sorted]

    # 2. Sample route points (every 5 miles is enough for station finding)
    # ORS returns many points, we only need a subset to find nearby stations
    sampled = []
    last_marker = -999
    for p in route_points:
        if p.cumulative_miles - last_marker >= 5:
            sampled.append(p)
            last_marker = p.cumulative_miles
    if route_points and route_points[-1] not in sampled:
        sampled.append(route_points[-1])

    # 3. Find nearby stations per point
    # Mapping of station object to (min_distance, best_mile_marker)
    found_map = {}
    
    # Degrees latitude roughly 69 miles, longitude varies but ~50 miles in US
    # We use a bounding box of ~25 miles to be safe
    PAD_LAT = 0.4 
    PAD_LON = 0.5

    for rp in sampled:
        # Binary search for stations in the latitude band
        idx_start = bisect_left(station_lats, rp.lat - PAD_LAT)
        idx_end = bisect_right(station_lats, rp.lat + PAD_LAT)
        
        for i in range(idx_start, idx_end):
            s = stations_sorted[i]
            
            # Quick longitude check
            if abs(s.lon - rp.lon) > PAD_LON:
                continue
            
            # Distance calculation
            dist = haversine_miles(s.lat, s.lon, rp.lat, rp.lon)
            
            if dist <= max_distance_miles:
                if s not in found_map or dist < found_map[s][0]:
                    found_map[s] = (dist, rp.cumulative_miles)

    # 4. Convert to CandidateStation objects
    candidate_stations = []
    for station, (dist, marker) in found_map.items():
        if dist <= 5:
            route_type = 'ON_ROUTE'
            detour_miles = 0
        else:
            route_type = 'DETOUR_POSSIBLE'
            detour_miles = dist
            
        candidate_stations.append(
            CandidateStation(station, route_type, detour_miles, marker)
        )

    return sorted(candidate_stations, key=lambda s: s.mile_marker)
