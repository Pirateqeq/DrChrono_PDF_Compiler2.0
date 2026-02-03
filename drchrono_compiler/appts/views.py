from datetime import datetime, timedelta
from django.views.generic import ListView
from django.contrib import messages
from verify.services import require_auth, get_valid_access_token
from verify.exceptions import DrChronoAuthError
from django.utils.decorators import method_decorator
import requests

@method_decorator(require_auth, name='dispatch')
class HistoricalAppointmentsView(ListView):
    template_name = 'appts/historical_list.html'
    context_object_name = 'appointments'

    # Verify DrChrono login access
    login_url = 'verify_app:connect_drchrono'
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        patient_id = self.kwargs['patient_id']

        try:
            token = get_valid_access_token(self.request)
            headers = {"Authorization": f"Bearer {token}"}

            three_years_ago = (datetime.now() - timedelta(days=365 * 3))
            since_str = three_years_ago.strftime('%Y-%m-%dT%H:%M:%S')

            params = {
                'patient': patient_id,
                'since': since_str,
                'verbose': "true",         
                'page_size': 50,                       
            }

            url = "https://app.drchrono.com/api/appointments"
            resp = requests.get(url, headers=headers, params=params, timeout=12)

            resp.raise_for_status()

            data = resp.json()
            all_appts = data.get('results', [])


            today_iso = datetime.now().date().isoformat()

            historical = []

            for appt in all_appts:
                # Get date string safely (prefer scheduled_time, fallback to date)
                appt_date_str = None
                if 'scheduled_time' in appt and appt['scheduled_time']:
                    appt_date_str = appt['scheduled_time'][:10]  # YYYY-MM-DD
                elif 'date' in appt and appt['date']:
                    appt_date_str = appt['date']

                if not appt_date_str or len(appt_date_str) < 10:
                    continue

                if appt_date_str > today_iso:
                    continue

                clinical_note = appt.get('clinical_note')
                if not clinical_note:
                    continue
                
                pdf_url = None
                if isinstance(clinical_note, dict):
                    pdf_url = clinical_note.get('pdf')
                elif isinstance(clinical_note, str) and clinical_note.startswith('http'):
                    pdf_url = clinical_note

                appt['scheduled_time'] = datetime.fromisoformat(appt['scheduled_time'])
                
                if pdf_url:
                    historical.append(appt)

            # Sort newest → oldest
            historical.sort(key=lambda a: a.get('scheduled_time', '9999-99-99'), reverse=True)

            return historical

        except DrChronoAuthError as e:
            messages.error(self.request, f"Authentication issue: {str(e)}. Please reconnect.")
            return []

        except requests.HTTPError as e:
            error_detail = e.response.text[:300] if e.response else "No detail"
            messages.error(self.request, f"DrChrono returned {e.response.status_code}: {error_detail}")
            print("Full API error response:", e.response.text)
            return []

        except Exception as e:
            messages.error(self.request, f"Failed to load appointments: {str(e)}")
            return []

    def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            
            patient_id = self.kwargs['patient_id']
            
            # Get from URL query params (safer than session for this)
            first_name = self.request.GET.get('first_name', '').strip()
            last_name  = self.request.GET.get('last_name', '').strip()
            
            # Build full name, fallback to patient ID if missing
            if first_name or last_name:
                patient_name = f"{first_name} {last_name}".strip()
            else:
                patient_name = f"Patient {patient_id}"
            
            context['patient_name'] = patient_name
            context['patient_id'] = patient_id
            context['page_title'] = f"Historical Appointments for {patient_name}"
            
            return context