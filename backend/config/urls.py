"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
import os

# Serve the frontend index.html from the frontend directory
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'frontend')


def serve_frontend(request):
    from django.http import FileResponse
    return FileResponse(open(os.path.join(FRONTEND_DIR, 'index.html'), 'rb'))


def serve_frontend_file(request, filename):
    from django.http import FileResponse, Http404
    filepath = os.path.join(FRONTEND_DIR, filename)
    if os.path.exists(filepath):
        return FileResponse(open(filepath, 'rb'))
    raise Http404


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/stations/', include('stations.urls')),
    path('api/', include('routes.urls')),
    path('<str:filename>', serve_frontend_file, name='frontend-file'),
    path('', serve_frontend, name='frontend'),
]
