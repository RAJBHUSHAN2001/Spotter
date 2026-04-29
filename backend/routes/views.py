from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from .algorithm.router import get_route
from .algorithm.station_filter import get_stations_near_route
from .algorithm.optimizer import optimize, calculate_naive_cost
from stations.models import FuelStation

import requests


class RouteView(APIView):
    """
    Primary orchestration endpoint for the Spotter Fuel Route Planner.
    
    This view handles coordinate acquisition (geocoding), polyline fetching,
    spatial filtering of fuel stations, and dual-strategy route optimization.
    """
    
    def post(self, request):
        """
        Process a routing request and return optimized itineraries and market insights.
        """
        start_address = request.data.get('start')
        end_address = request.data.get('end')
        start_coords = request.data.get('start_coords')
        end_coords = request.data.get('end_coords')

        if not start_address or not end_address:
            return Response(
                {"error": "Start and End locations are required."}, status=400)

        # Geocode if coordinates not provided
        def geocode(address):
            if not address:
                return None
                
            # Try 1: OpenRouteService Geocoding (Very smart, forgiving of "USA" suffixes)
            api_key = getattr(settings, 'OPENROUTESERVICE_API_KEY', '')
            if api_key and api_key != 'your_openrouteservice_api_key_here':
                try:
                    resp = requests.get(
                        "https://api.openrouteservice.org/geocode/search", 
                        params={"api_key": api_key, "text": address, "boundary.country": "US", "size": 1},
                        timeout=5
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('features'):
                            coords = data['features'][0]['geometry']['coordinates']
                            return [float(coords[0]), float(coords[1])]
                except Exception as e:
                    print(f"DEBUG: ORS Geocode failed: {e}")

            # Try 2: Fallback to Nominatim (with cleaned query and strict country code)
            headers = {"User-Agent": "FuelRoutePlanner/1.0"}
            query = address.replace(", United States", "").replace(", USA", "").replace(" United States", "").replace(" USA", "").strip()
            
            coords = None
            try:
                resp = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": query, "format": "json", "countrycodes": "us", "limit": 1},
                    headers=headers,
                    timeout=5
                )
                if resp.status_code == 200 and resp.json():
                    coords = [float(resp.json()[0]['lon']), float(resp.json()[0]['lat'])]
            except Exception as e:
                print(f"DEBUG: Nominatim Geocode failed: {e}")
                
            return coords

        if not start_coords:
            start_coords = geocode(start_address)
        if not end_coords:
            end_coords = geocode(end_address)

        if not start_coords or not end_coords:
            return Response(
                {"error": "Could not geocode locations. Please try a more specific address."}, status=400)

        # CRITICAL FIX: Ensure coordinates are perfectly snapped to a drivable road
        # to prevent OpenRouteService 350m limit errors in rural areas.
        def snap_to_road(coords):
            if not coords: return coords
            try:
                osrm_url = f"https://router.project-osrm.org/nearest/v1/driving/{coords[0]},{coords[1]}"
                resp = requests.get(osrm_url, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('code') == 'Ok' and data.get('waypoints'):
                        return data['waypoints'][0]['location']
            except Exception as e:
                print(f"DEBUG: OSRM snapping failed: {e}")
            return coords

        def snap_waypoints(coords_list):
            snapped = []
            for coords in coords_list:
                snapped.append(snap_to_road(coords))
            return snapped

        start_coords = snap_to_road(start_coords)
        end_coords = snap_to_road(end_coords)

        # Validate API key first
        api_key = getattr(settings, 'OPENROUTESERVICE_API_KEY', '')
        if not api_key or api_key == 'your_openrouteservice_api_key_here':
            return Response({
                "error": "OpenRouteService API key is missing or invalid. "
                         "Please add a real ORS_API_KEY to your backend/.env file. "
                         "Get a free key at: https://openrouteservice.org"
            }, status=503)

        # 1. Get Route
        try:
            route_points, raw_polyline, duration_seconds = get_route(
                start_coords, end_coords, api_key)
        except Exception as e:
            return Response({"error": f"Routing failed: {str(e)}"}, status=502)
        total_miles = route_points[-1].cumulative_miles if route_points else 0

        # Format travel time
        def format_duration(secs):
            if not secs:
                # Estimate: avg 55 mph for trucks
                secs = int((total_miles / 55) * 3600)
            h = secs // 3600
            m = (secs % 3600) // 60
            if h > 0:
                return f"{h}h {m}m"
            return f"{m}m"

        # 2. Filter Stations (Cached for extreme performance)
        from django.core.cache import cache
        all_stations = cache.get('all_fuel_stations')
        if not all_stations:
            all_stations = list(FuelStation.objects.filter(lat__isnull=False, lon__isnull=False))
            cache.set('all_fuel_stations', all_stations, 86400) # Cache for 24 hours

        candidate_stations = get_stations_near_route(
            route_points, all_stations)

        # 3. Optimize
        starting_fuel_pct = float(request.data.get('starting_fuel_pct', 100.0))
        starting_fuel_pct = max(1.0, min(100.0, starting_fuel_pct)) # bound between 1% and 100%
        
        # 3. Optimize Both Strategies
        try:
            stops_max_save, cost_max_save = optimize(total_miles, candidate_stations, starting_fuel_pct, strategy="max_save")
            stops_fastest, cost_fastest = optimize(total_miles, candidate_stations, starting_fuel_pct, strategy="fastest")
        except Exception as e:
            return Response({"error": str(e)}, status=400)

        # 4. Naive cost
        naive_cost = calculate_naive_cost(total_miles, candidate_stations, starting_fuel_pct)

        # Helper to format response
        avg_price = sum(s.retail_price for s in all_stations) / len(all_stations) if all_stations else 3.50
        def format_stops(chosen_stops):
            resp = []
            cheapest = min((s['station'].station.retail_price for s in chosen_stops), default=float('inf'))
            for i, stop_data in enumerate(chosen_stops):
                st = stop_data['station']
                s = st.station
                resp.append({
                    "order": i + 1,
                    "name": s.name,
                    "city": s.city,
                    "state": s.state,
                    "price_per_gallon": round(s.retail_price, 2),
                    "gallons_to_buy": round(stop_data['gallons'], 2),
                    "cost_at_stop": round(stop_data['cost'], 2),
                    "cost_at_stop_display": f"${round(stop_data['cost'], 2):.2f}",
                    "miles_along_route": round(st.mile_marker, 1),
                    "miles_from_route": round(st.detour_miles, 1),
                    "detour_taken": st.route_type == 'DETOUR_POSSIBLE',
                    "tank_on_arrival_miles": round(stop_data['tank_on_arrival'], 1),
                    "tank_on_departure_miles": round(stop_data['tank_on_departure'], 1),
                    "lat": s.lat,
                    "lon": s.lon,
                    "decision_reason": stop_data['decision_reason'],
                    "is_cheapest_overall": s.retail_price == cheapest,
                    "savings_vs_naive": round(stop_data['gallons'] * max(0, avg_price - s.retail_price), 2)
                })
            return resp

        # 5. Get Exact Multi-Stop Polylines
        from .algorithm.router import get_multi_stop_route
        
        polyline_max_save = raw_polyline
        duration_max_save = duration_seconds
        if stops_max_save:
            wp = [start_coords] + [[s['station'].station.lon, s['station'].station.lat] for s in stops_max_save] + [end_coords]
            wp = snap_waypoints(wp)
            exact_coords, exact_dur = get_multi_stop_route(wp, api_key)
            if exact_coords: 
                polyline_max_save = exact_coords
                duration_max_save = exact_dur
            
        polyline_fastest = raw_polyline
        duration_fastest = duration_seconds
        if stops_fastest:
            wp = [start_coords] + [[s['station'].station.lon, s['station'].station.lat] for s in stops_fastest] + [end_coords]
            wp = snap_waypoints(wp)
            exact_coords, exact_dur = get_multi_stop_route(wp, api_key)
            if exact_coords: 
                polyline_fastest = exact_coords
                duration_fastest = exact_dur

        total_gallons = total_miles / 10.0

        # 6. Generate Advanced Insights
        import statistics
        all_candidate_prices = [s.station.retail_price for s in candidate_stations]
        price_volatility = statistics.stdev(all_candidate_prices) if len(all_candidate_prices) > 1 else 0
        
        # Group by state for cheapest state
        state_prices = {}
        for s in candidate_stations:
            st = s.station.state
            price = s.station.retail_price
            if st not in state_prices: state_prices[st] = []
            state_prices[st].append(price)
        
        cheapest_state = "N/A"
        if state_prices:
            avg_state_prices = {st: sum(p)/len(p) for st, p in state_prices.items()}
            cheapest_state = min(avg_state_prices, key=avg_state_prices.get)

        def get_insights(chosen_stops, cost):
            total_detour_miles = sum(s['station'].detour_miles for s in chosen_stops)
            return {
                "stations_considered": len(candidate_stations),
                "stations_on_route": sum(1 for s in candidate_stations if s.route_type == 'ON_ROUTE'),
                "stations_rejected_expensive": len(candidate_stations) - len(chosen_stops),
                "detours_evaluated": sum(1 for s in candidate_stations if s.route_type == 'DETOUR_POSSIBLE'),
                "detours_taken": sum(1 for s in chosen_stops if s['station'].route_type == 'DETOUR_POSSIBLE'),
                "detours_rejected": sum(1 for s in candidate_stations if s.route_type == 'DETOUR_POSSIBLE') - sum(1 for s in chosen_stops if s['station'].route_type == 'DETOUR_POSSIBLE'),
                "money_saved_vs_naive_display": f"${round(max(0, naive_cost - cost), 2):.2f}",
                "avg_price_found": round(sum(all_candidate_prices) / len(all_candidate_prices), 3) if all_candidate_prices else 0,
                "best_price_found": round(min(all_candidate_prices, default=0), 3),
                "avg_savings_per_gallon": round(max(0, (naive_cost - cost) / (total_gallons or 1)), 3),
                "efficiency_score": round(min(100, (cost / naive_cost * 100)) if naive_cost > 0 else 100, 1),
                "price_volatility": round(price_volatility, 3),
                "cheapest_state": cheapest_state,
                "total_detour_miles": round(total_detour_miles, 1)
            }

        return Response({
            "trip": {
                "start": start_address,
                "end": end_address,
                "total_miles": round(total_miles, 1),
                "total_gallons": round(total_gallons, 1),
                "naive_cost_display": f"${round(naive_cost, 2):.2f}",
                "travel_time": format_duration(duration_seconds),
                "travel_time_seconds": duration_seconds,
            },
            "max_save": {
                "total_cost": round(cost_max_save, 2),
                "total_cost_display": f"${round(cost_max_save, 2):.2f}",
                "money_saved": f"${round(naive_cost - cost_max_save, 2):.2f}",
                "fuel_stops": format_stops(stops_max_save),
                "polyline": [[float(c[1]), float(c[0])] for c in polyline_max_save],
                "travel_time": format_duration(duration_max_save),
                "insights": get_insights(stops_max_save, cost_max_save)
            },
            "fastest": {
                "total_cost": round(cost_fastest, 2),
                "total_cost_display": f"${round(cost_fastest, 2):.2f}",
                "money_saved": f"${round(naive_cost - cost_fastest, 2):.2f}",
                "fuel_stops": format_stops(stops_fastest),
                "polyline": [[float(c[1]), float(c[0])] for c in polyline_fastest],
                "travel_time": format_duration(duration_fastest),
                "insights": get_insights(stops_fastest, cost_fastest)
            },
            "route": {
                "start_coords": [float(start_coords[1]), float(start_coords[0])],
                "end_coords": [float(end_coords[1]), float(end_coords[0])]
            }
        })
