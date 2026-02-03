from django.urls import path
from . import views

app_name = 'appts'

urlpatterns = [
    path('patient/<int:patient_id>/historical/', views.HistoricalAppointmentsView.as_view(), name='historical_list'),

]