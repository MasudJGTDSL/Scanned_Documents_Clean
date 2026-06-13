from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('process/', views.process, name='process'),
    path('job/<str:job_id>/', views.job_status, name='job_status'),
    path('api/job/<str:job_id>/', views.job_api, name='job_api'),
    path('api/job/<str:job_id>/open-folder/', views.open_folder, name='open_folder'),
    path('api/browse-folder/', views.browse_folder, name='browse_folder'),
]
