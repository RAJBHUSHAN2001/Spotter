from django.urls import path
from .views import StationListView, StationAddView, StationDeleteView

urlpatterns = [
    path('', StationListView.as_view(), name='station-list'),
    path('add/', StationAddView.as_view(), name='station-add'),
    path('<int:pk>/', StationDeleteView.as_view(), name='station-delete'),
]
