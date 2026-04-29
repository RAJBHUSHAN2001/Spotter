from django.core.management.base import BaseCommand
from stations.models import FuelStation
import requests
import time


class Command(BaseCommand):
    help = 'Geocode stations using Nominatim'

    def handle(self, *args, **options):
        stations = FuelStation.objects.filter(geocoded=False)
        total = stations.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS(
                'No stations left to geocode!'))
            return

        self.stdout.write(f'Geocoding {total} stations...')

        NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "FuelRoutePlanner/1.0"}

        count = 0
        for station in stations:
            # According to prompt: Geocode using "City, State, USA" as primary query.
            # Address field used only as fallback/hint.
            query = f"{station.city}, {station.state}, USA"
            params = {
                "q": query,
                "format": "json",
                "limit": 1,
                "countrycodes": "us"
            }

            try:
                response = requests.get(
                    NOMINATIM_URL, params=params, headers=headers)
                results = response.json()

                if results:
                    station.lat = float(results[0]['lat'])
                    station.lon = float(results[0]['lon'])
                    station.geocoded = True
                    station.save()
                else:
                    # Fallback to state only
                    fallback_query = f"{station.state}, USA"
                    params["q"] = fallback_query
                    time.sleep(1)  # respect limit before fallback

                    response = requests.get(
                        NOMINATIM_URL, params=params, headers=headers)
                    results = response.json()

                    if results:
                        station.lat = float(results[0]['lat'])
                        station.lon = float(results[0]['lon'])
                        station.geocoded = True
                        station.save()
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f'Could not geocode station {
                                    station.id}'))
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error geocoding station {
                            station.id}: {e}'))

            count += 1
            if count % 100 == 0:
                self.stdout.write(f'Geocoded {count}/{total} stations')

            time.sleep(1)  # IMPORTANT: Nominatim requirement

        self.stdout.write(self.style.SUCCESS('Finished geocoding!'))
