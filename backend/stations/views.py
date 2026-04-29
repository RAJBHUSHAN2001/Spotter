from rest_framework.views import APIView
from rest_framework.response import Response
from .models import FuelStation


class StationListView(APIView):
    def get(self, request):
        state = request.query_params.get('state')
        min_price = request.query_params.get('min_price')
        max_price = request.query_params.get('max_price')
        custom_only = request.query_params.get('custom_only')

        stations = FuelStation.objects.all()

        if state:
            stations = stations.filter(state__iexact=state)
        if min_price:
            stations = stations.filter(retail_price__gte=min_price)
        if max_price:
            stations = stations.filter(retail_price__lte=max_price)
        if custom_only == 'true':
            stations = stations.filter(is_custom=True)

        data = []
        for s in stations[:100]:  # limit to 100 for perf in list view
            data.append({
                "id": s.id,
                "name": s.name,
                "city": s.city,
                "state": s.state,
                "price_per_gallon": s.retail_price,
                "lat": s.lat,
                "lon": s.lon,
                "is_custom": s.is_custom
            })

        return Response({
            "count": stations.count(),
            "stations": data
        })


class StationAddView(APIView):
    def post(self, request):
        name = request.data.get('name')
        address = request.data.get('address')
        city = request.data.get('city')
        state = request.data.get('state')
        price = request.data.get('price_per_gallon')

        # simplified custom id logic
        new_id = FuelStation.objects.count() + 100000

        # We'd typically geocode here for real app, but for now just mock or
        # leave blank
        lat, lon = 40.0, -100.0  # Mock

        s = FuelStation.objects.create(
            opis_id=new_id,
            name=name,
            address=address,
            city=city,
            state=state,
            retail_price=price,
            lat=lat,
            lon=lon,
            is_custom=True,
            geocoded=True
        )

        return Response({
            "success": True,
            "station": {
                "id": s.id,
                "name": s.name,
                "city": s.city,
                "state": s.state,
                "price_per_gallon": s.retail_price,
                "lat": s.lat,
                "lon": s.lon,
                "is_custom": s.is_custom
            }
        })


class StationDeleteView(APIView):
    def delete(self, request, pk):
        try:
            s = FuelStation.objects.get(pk=pk, is_custom=True)
            s.delete()
            return Response({"success": True, "message": "Station removed"})
        except FuelStation.DoesNotExist:
            return Response(
                {"success": False, "message": "Station not found or not custom"}, status=404)
