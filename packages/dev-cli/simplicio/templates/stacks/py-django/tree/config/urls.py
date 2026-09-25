from django.urls import path

from app.views import health


urlpatterns = [
    path("health/", health, name="health"),
]
