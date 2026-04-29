import csv
from django.core.management.base import BaseCommand
from stations.models import FuelStation


class Command(BaseCommand):
    help = 'Load fuel stations from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, help='The CSV file to load')

    def handle(self, *args, **options):
        file_path = options['file']
        if not file_path:
            self.stdout.write(self.style.ERROR(
                'Please provide a file with --file'))
            return

        CANADIAN_PROVINCES = ['AB', 'BC', 'MB',
                              'NB', 'NS', 'ON', 'QC', 'SK', 'YT']

        # Step 1: Read CSV
        with open(file_path, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))

        # Step 2: Filter out Canadian stations
        us_rows = [r for r in rows if r['State'].strip()
                   not in CANADIAN_PROVINCES]

        # Step 3: Clean whitespace on ALL string fields
        for row in us_rows:
            for key in row:
                row[key] = row[key].strip()

        # Step 4: Deduplicate by OPIS ID — keep lowest price
        from collections import defaultdict
        by_opis = defaultdict(list)
        for row in us_rows:
            by_opis[row['OPIS Truckstop ID']].append(row)

        unique_stations = []
        for opis_id, dupes in by_opis.items():
            best = min(dupes, key=lambda r: float(r['Retail Price']))
            unique_stations.append(best)

        # Step 5: Bulk insert
        objs = [
            FuelStation(
                opis_id=int(s['OPIS Truckstop ID']),
                name=s['Truckstop Name'],
                address=s['Address'],
                city=s['City'],
                state=s['State'],
                rack_id=int(s['Rack ID']) if s['Rack ID'] else None,
                retail_price=float(s['Retail Price']),
                is_custom=False,
                geocoded=False,
            )
            for s in unique_stations
        ]

        # In SQLite (which doesn't support ON CONFLICT DO UPDATE like Postgres out of the box),
        # ignore_conflicts=True will skip duplicates based on the unique
        # constraint.
        FuelStation.objects.bulk_create(objs, ignore_conflicts=True)

        self.stdout.write(
            self.style.SUCCESS(
                f'✅ Loaded {
                    len(objs)} unique US fuel stations into DB'))
        self.stdout.write(
            self.style.SUCCESS(
                f'   (Skipped {
                    len(rows) -
                    len(objs)} rows: duplicates + Canadian)'))
