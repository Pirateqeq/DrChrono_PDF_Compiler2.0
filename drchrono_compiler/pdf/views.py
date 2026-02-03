from django.views import View
from django.http import HttpResponse
from django.contrib import messages
from django.shortcuts import redirect
from verify.services import require_auth, get_valid_access_token
from django.utils.decorators import method_decorator
from pypdf import PdfWriter
from .services import (
    generate_balance_report,
    generate_clinical_notes,
    fetch_hcfa_data,
    generage_hcfa_bill,
)
from io import BytesIO
import requests

@method_decorator(require_auth, name='dispatch')
class GenerateSelectedPDFView(View):

    # Verify DrChrono login access
    login_url = 'verify_app:connect_drchrono'
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def post(self, request, patient_id):
        selected_ids = request.POST.getlist('selected_appts')
        if not selected_ids:
            messages.warning(request, "No appointments were selected for PDF generation.")
            return redirect('appts:historical_list', patient_id=patient_id)

        try:
            selected_ids = list(reversed(selected_ids))
            token = get_valid_access_token(request)
            headers = {"Authorization": f"Bearer {token}"}

            merger = PdfWriter()

            balance_buffer = generate_balance_report(patient_id, token)
            merger.append(balance_buffer)

            # Pull appointment JSONs and key them into -> selected_appts{ APPT_ID : APPT_JSON }. Note - Later seperate pull into service file to include exception checks.
            # If appointment JSON is pulled properly key line_item into -> line_items{ APPT_ID : LINE_ITEM_JSON}. Note - Later seperate pull into service file to include exception checks.
            line_items = {}
            selected_appts = {}
            for appt_id in selected_ids:
                url = f"https://app.drchrono.com/api/appointments/{appt_id}?verbose=true"
                resp = requests.get(url, headers=headers)
                if resp.status_code == 200:
                    selected_appts[appt_id] = resp.json()
                    url = f"https://app.drchrono.com/api/line_items?appointment={appt_id}"
                    resp = requests.get(url, headers=headers)
                    if resp.status_code == 200:
                        line_items[appt_id] = resp.json().get('results')[0]
                    else:
                        messages.warning(request, f'Could not fetch transaction details for {appt_id}. Response status {resp.text}. - skipped.')
                else:
                    messages.warning(request, f'Could not fetch appointment for {appt_id}. Response status {resp.text}. - skipped.')

            # Pull patient JSON. Note - Later seperate pull into service file to include exception checks.
            patient_json = {}
            url = f"https://app.drchrono.com/api/patients/{patient_id}"
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                patient_json = resp.json()
            else:
                messages.warning(request, f'Could not fetch patient information for {patient_id}. Response status {resp.text}. - skipped. ')

            # Pull doctor JSON. Note - Later seperate pull into service file to include exception checks (Implement Later).

            for appt_id in selected_appts:
                merger.append(generate_clinical_notes(request, selected_appts[appt_id]))
                hcfa_data = fetch_hcfa_data(patient_json, selected_appts[appt_id], line_items[appt_id])
                merger.append(generage_hcfa_bill(request, hcfa_data))

            output = BytesIO()
            merger.write(output)
            merger.close()
            output.seek(0)

            response = HttpResponse(content_type='application/pdf')
            filename = f"Patient_{patient_json.get('first_name')}_{patient_json.get('last_name')}_REPORT.pdf"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response.write(output.read())

            return response

        except Exception as e:
            messages.error(request, f"PDF generation failed: {str(e)}.")
            return redirect('appts:historical_list', patient_id=patient_id)