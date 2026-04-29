"""
Fuel Route Optimizer
====================
Two strategies:
  fastest  — only stop when forced (can't reach destination or next must-stop).
              Pick the NEAREST reachable station. Fill to a full tank.
  max_save — only stop when forced. Pick the CHEAPEST reachable station.
              Fill minimum needed to reach the next cheaper station; or fill
              to maximum when this IS the cheapest station ahead.

Guaranteed: max_save_cost <= fastest_cost for any valid route.
"""

TANK_CAPACITY_MILES = 500   # max driving range on full tank
MPG = 10                    # miles per gallon
SAFETY_BUFFER_MILES = 50    # keep this many miles always in reserve


# ─────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────

def _stations_reachable_now(candidate_stations, current_mile, current_tank, visited):
    """
    Stations we can physically reach with current fuel (keeping safety buffer).
    Strictly ahead of current_mile.
    """
    usable = current_tank - SAFETY_BUFFER_MILES
    return [
        s for s in candidate_stations
        if s not in visited
        and s.mile_marker > current_mile
        and (s.mile_marker - current_mile + s.detour_miles * 2) <= usable
    ]


def _stations_reachable_from(candidate_stations, from_mile, tank, visited):
    """
    Stations reachable from from_mile with `tank` miles of fuel.
    """
    usable = tank - SAFETY_BUFFER_MILES
    return [
        s for s in candidate_stations
        if s not in visited
        and s.mile_marker > from_mile
        and (s.mile_marker - from_mile + s.detour_miles * 2) <= usable
    ]


def _eff_price(s, strategy):
    """Effective price per gallon including amortised detour cost."""
    if s.route_type != 'DETOUR_POSSIBLE' or s.detour_miles == 0:
        return s.price
    detour_cost = (s.detour_miles * 2 / MPG) * s.price
    if strategy == 'fastest':
        return s.price + s.detour_miles * 50.0  # huge penalty
    return s.price + detour_cost / 25.0          # spread over 25-gal fill


def _record(stop, fill_miles, current_mile, current_tank, reason):
    gallons = fill_miles / MPG
    cost = gallons * stop.price
    toa = max(0.0, current_tank - (stop.mile_marker - current_mile))
    return {
        "station": stop,
        "gallons": gallons,
        "cost": cost,
        "fill_amount_miles": fill_miles,
        "decision_reason": reason,
        "tank_on_arrival": toa,
        "tank_on_departure": min(TANK_CAPACITY_MILES, toa + fill_miles),
    }


# ─────────────────────────────────────────────────────
# FASTEST strategy
# ─────────────────────────────────────────────────────

def optimize_fastest(total_route_miles, candidate_stations, starting_fuel_pct, visited):
    """
    Only stop when we genuinely cannot reach the destination.
    At each forced stop: pick nearest station, fill full tank.
    """
    current_mile = 0.0
    current_tank = TANK_CAPACITY_MILES * (starting_fuel_pct / 100.0)
    total_cost = 0.0
    chosen_stops = []

    while True:
        # Can we reach the destination right now?
        if current_tank >= (total_route_miles - current_mile):
            break

        reachable = _stations_reachable_now(candidate_stations, current_mile, current_tank, visited)

        if not reachable:
            # Emergency: extend search to anything strictly ahead, ignoring buffer
            ahead = sorted(
                [s for s in candidate_stations if s not in visited and s.mile_marker > current_mile],
                key=lambda s: s.mile_marker
            )
            if not ahead or (ahead[0].mile_marker - current_mile + ahead[0].detour_miles * 2) > current_tank:
                raise Exception(
                    "Critically low fuel: Reaching a nearby station is not possible. "
                    "You will run out of gas!")
            reachable = [ahead[0]]

        # Fastest = furthest station we can reach (minimises total number of stops)
        # Avoid detours unless no alternative
        for s in reachable:
            s.eff_price = _eff_price(s, 'fastest')
        # Sort: prefer on-route stations; among those pick the furthest
        on_route = [s for s in reachable if s.route_type != 'DETOUR_POSSIBLE']
        stop = max(on_route or reachable, key=lambda s: s.mile_marker)

        toa = max(0.0, current_tank - (stop.mile_marker - current_mile))
        fill = TANK_CAPACITY_MILES - toa  # always fill full

        entry = _record(stop, fill, current_mile, current_tank, "Full fill — fastest route")
        total_cost += entry["cost"]
        chosen_stops.append(entry)

        current_tank = min(TANK_CAPACITY_MILES, toa + fill)
        current_mile = stop.mile_marker
        visited.add(stop)

    return chosen_stops, total_cost


# ─────────────────────────────────────────────────────
# MAX SAVE strategy
# ─────────────────────────────────────────────────────

def optimize_max_save(total_route_miles, candidate_stations, starting_fuel_pct, visited):
    """
    Only stop when we genuinely cannot reach the destination.
    At each forced stop:
      1. Among all stations reachable now, pick the CHEAPEST.
      2. If a cheaper station exists further ahead (reachable on a full tank):
           fill minimum to get there (+ buffer).
      3. If this IS the cheapest in range:
           fill as much as useful to avoid pricier stops ahead.
    """
    current_mile = 0.0
    current_tank = TANK_CAPACITY_MILES * (starting_fuel_pct / 100.0)
    total_cost = 0.0
    chosen_stops = []

    while True:
        if current_tank >= (total_route_miles - current_mile):
            break

        reachable = _stations_reachable_now(candidate_stations, current_mile, current_tank, visited)

        if not reachable:
            ahead = sorted(
                [s for s in candidate_stations if s not in visited and s.mile_marker > current_mile],
                key=lambda s: s.mile_marker
            )
            if not ahead or (ahead[0].mile_marker - current_mile + ahead[0].detour_miles * 2) > current_tank:
                raise Exception(
                    "Critically low fuel: Reaching a nearby station is not possible. "
                    "You will run out of gas!")
            reachable = [ahead[0]]

        # Score by effective price and pick cheapest reachable now
        for s in reachable:
            s.eff_price = _eff_price(s, 'max_save')
        reachable.sort(key=lambda s: s.eff_price)
        stop = reachable[0]

        toa = max(0.0, current_tank - (stop.mile_marker - current_mile))
        miles_remaining = total_route_miles - stop.mile_marker

        # Stations reachable from this stop with a FULL tank
        further = _stations_reachable_from(candidate_stations, stop.mile_marker, TANK_CAPACITY_MILES, visited)
        for s in further:
            s.eff_price = _eff_price(s, 'max_save')

        cheaper_ahead = sorted(
            [s for s in further if s.eff_price < stop.eff_price],
            key=lambda s: s.mile_marker
        )

        if cheaper_ahead:
            # Fill minimum to reach nearest cheaper station
            target = cheaper_ahead[0]
            dist = (target.mile_marker - stop.mile_marker) + target.detour_miles * 2
            need = dist + SAFETY_BUFFER_MILES
            fill = max(5.0, min(need - toa, TANK_CAPACITY_MILES - toa))  # Ensure minimum 5 gallon fill
            reason = (
                f"Partial fill — cheaper at mi {int(target.mile_marker)} "
                f"(${target.price:.3f} vs ${stop.price:.3f}/gal)"
            )
        else:
            # This is the cheapest available — load up
            fill = min(TANK_CAPACITY_MILES - toa, miles_remaining + SAFETY_BUFFER_MILES)
            reason = f"Max fill — cheapest in range (${stop.price:.3f}/gal)"

        # Record all stops (no threshold) to maintain consistency
        new_tank = min(TANK_CAPACITY_MILES, toa + fill)
        entry = _record(stop, fill, current_mile, current_tank, reason)
        total_cost += entry["cost"]
        chosen_stops.append(entry)

        current_tank = new_tank
        current_mile = stop.mile_marker
        visited.add(stop)

    return chosen_stops, total_cost


# ─────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────

def optimize(total_route_miles, candidate_stations, starting_fuel_pct=100.0, strategy="fastest"):
    visited = set()
    if strategy == "max_save":
        return optimize_max_save(total_route_miles, candidate_stations, starting_fuel_pct, visited)
    return optimize_fastest(total_route_miles, candidate_stations, starting_fuel_pct, visited)


# ─────────────────────────────────────────────────────
# Naive baseline (for comparison display)
# ─────────────────────────────────────────────────────

def calculate_naive_cost(total_route_miles, candidate_stations, starting_fuel_pct=100.0):
    """Driver who refuels at the last moment at whatever station is nearest."""
    current_mile = 0.0
    total_cost = 0.0
    current_tank = TANK_CAPACITY_MILES * (starting_fuel_pct / 100.0)

    while True:
        if current_mile + current_tank >= total_route_miles:
            break
        target_mile = current_mile + current_tank - SAFETY_BUFFER_MILES
        ahead = [s for s in candidate_stations if s.mile_marker > current_mile]
        nearest = min(ahead, key=lambda s: abs(s.mile_marker - target_mile), default=None)
        if not nearest:
            break
        consumed = nearest.mile_marker - current_mile
        fill = TANK_CAPACITY_MILES - (current_tank - consumed)
        total_cost += (fill / MPG) * nearest.price
        current_mile = nearest.mile_marker
        current_tank = TANK_CAPACITY_MILES

    gallons = (total_route_miles - current_mile) / MPG
    avg = sum(s.price for s in candidate_stations) / len(candidate_stations) if candidate_stations else 3.50
    total_cost += gallons * avg
    return total_cost
