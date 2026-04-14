from django.urls import path
from . import views_ui

urlpatterns = [
    path('', views_ui.DashboardView.as_view(), name='dashboard'),
    path('activities/', views_ui.ActivityListView.as_view(), name='activity-list'),
    path('activities/<int:pk>/', views_ui.ActivityDetailView.as_view(), name='activity-detail'),
    path('charts/', views_ui.ChartsView.as_view(), name='charts'),
    path('api/load-athlete/', views_ui.load_athlete_api, name='api-load-athlete'),
    path('api/detect-missing/', views_ui.detect_missing_api, name='api-detect-missing'),
    path('api/load-missing/', views_ui.load_missing_api, name='api-load-missing'),
    path('api/status/', views_ui.status_api, name='api-status'),
]
