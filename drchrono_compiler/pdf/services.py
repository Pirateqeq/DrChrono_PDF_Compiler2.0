from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from io import BytesIO

import requests
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

def generate_balance_report(patient_id: int, token: str, provider_name: str = "Emily Kurokawa") -> BytesIO:
    """
    Generate a clean, well-aligned balance report PDF matching the desired layout.
    """
    headers = {"Authorization": f"Bearer {token}"}
    buffer = BytesIO()

    # ── Fetch patient
    patient_url = f"https://app.drchrono.com/api/patients/{patient_id}"
    patient_resp = requests.get(patient_url, headers=headers, timeout=10)
    patient = patient_resp.json() if patient_resp.status_code == 200 else {}

    patient_name = f"{patient.get('last_name', '')}, {patient.get('first_name', '')}".strip() or "Unknown Patient"

    # ── Fetch appointments
    lookback_days = 365 * 3
    since = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%dT00:00:00")
    appts_url = (
        f"https://app.drchrono.com/api/appointments"
        f"?patient={patient_id}"
        f"&since={since}"
        f"&page_size=50"
        f"&ordering='-scheduled_time'"
        f"&verbose=true"
    )
    appts_resp = requests.get(appts_url, headers=headers, timeout=12)

    if appts_resp.status_code != 200:
        appointments = []
    else:
        appointments = appts_resp.json().get("results", [])

    today_iso = datetime.now().date().isoformat()
    valid_appts = []
    for appt in appointments:
        # Check date
        appt_date_str = appt.get("scheduled_time", "")[:10] or appt.get("date", "")
        if appt_date_str > today_iso:
            continue

        # Check for clinical note PDF
        clinical_note = appt.get('clinical_note')
        if not clinical_note:
            continue

        pdf = clinical_note.get('pdf')

        if pdf == 'None' or pdf is None:
            continue

        valid_appts.append(appt)

    #Sort valid appointments
    valid_appts = sorted(valid_appts, key=lambda x: x['scheduled_time'], reverse=True)
    # ── Fetch line items ──────────────────────────────────────────────────────────
    transactions = []
    for appt in valid_appts:
        appt_id = appt.get("id")

        line_url = f"https://app.drchrono.com/api/line_items?appointment={appt_id}"
        line_resp = requests.get(line_url, headers=headers)

        if line_resp.status_code == 200:
            items = line_resp.json().get("results", [])
            for item in items:
                item['reason'] = appt.get('reason', '---')
                transactions.append(item)
    # ── Calculate total balance ──────────────────────────────────────────────────
    total_balance = Decimal("0.00")
    for transaction in transactions:
        total_balance += Decimal(str(transaction.get("balance_total", "0")))
    transactions = sorted(transactions, key=lambda x: x['service_date'], reverse=True)

    # ── Build history rows ───────────────────────────────────────────────────────
    history_rows = []
    for tx in transactions:
        date_str = tx.get("service_date", "—")
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            display_date = date_obj.strftime("%b %d, %Y")
            desc_date = date_obj.strftime("%m/%d/%y")
        except Exception:
            display_date = date_str
            desc_date = date_str

        try:
            debit = Decimal(tx.get("balance_total", "0"))
            debit_str = f"${debit:,.2f}"
        except InvalidOperation:
            debit_str = "—"

        description = Paragraph(
            f"Appointment [{tx.get('appointment', '—')}] {desc_date} "
            f"{patient_name}: {tx.get('reason', '—')} Code {tx.get('code', '—')}"
        )

        history_rows.append([display_date, debit_str, "Auto Accident Claim", description])

    # ── Build PDF ────────────────────────────────────────────────────────────────
    REPORT_SIZE = (620, 800)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=REPORT_SIZE,
        leftMargin=18,
        rightMargin=18,
        topMargin=36,
        bottomMargin=36,
    )

    elements = []
    styles = getSampleStyleSheet()
    desc_style = styles['Normal']
    desc_style.fontSize = 9
    desc_style.leading = 11


    # Header
    elements.append(Paragraph("Patient Account Balance", styles["Heading1"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph(f"Provider: {provider_name}", styles["Normal"]))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(f"Patient: {patient_name}", styles["Normal"]))
    elements.append(Spacer(1, 8))

    # Account Balance
    elements.append(Paragraph("Account Balance:", styles["Heading2"]))
    elements.append(Paragraph(f"${total_balance:,.2f}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    # Payment History
    elements.append(Paragraph("Payment History:", styles["Heading2"]))
    elements.append(Spacer(1, 16))

    
    # Table - fixed widths for alignment
    table_data = [["Date", "Debit", "Auto Accident Claim", "Description"]] + history_rows

    if not history_rows:
        table_data.append(["—", "—", "—", "No billable transactions found."])

    table = Table(table_data, colWidths=[96, 96, 128, 256])

    table.setStyle(TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), colors.white),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),

        # Body
        ("WORDWRAP", (3, 0), (3, -1), True),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),     # Date
        ("ALIGN", (1, 1), (1, -1), "CENTER"),    # Debit
        ("ALIGN", (2, 1), (2, -1), "CENTER"),     # Type
        ("ALIGN", (3, 1), (3, -1), "LEFT", styles['Normal']),     # Description
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 36))

    doc.build(elements)
    buffer.seek(0)

    return buffer

from io import BytesIO
import requests
from django.contrib import messages

def generate_clinical_notes(request, appt: dict) -> BytesIO:
    """
    Input appointment dict, return clinical notes in Bytes, if exception return nothing and print message warning.
    """
    appt_id = appt['id']

    # Fetch clinical note PDF URL
    pdf_url = appt.get('clinical_note', {}).get('pdf')
    if not pdf_url:
        messages.warning(request, f"No clinical note PDF found for appointment {appt_id} – skipped.")
        return BytesIO()

    # Download and append clinical note PDF
    note_resp = requests.get(pdf_url, timeout=15)
    if note_resp.status_code == 200:
        note_buffer = BytesIO(note_resp.content)
        return note_buffer
    else:
        messages.warning(request, f"Failed to download clinical note for {appt_id}")
        return BytesIO()

def fetch_hcfa_data(patient_json, appt_json, line_item_json) -> dict:
    """
    Input patient, appointment and line item JSON, return formated data
    """
    
    data = {
        #Top Section
        'patient_name': f"{patient_json.get('last_name', '')}, {patient_json.get('first_name', '')}",
        'patient_dob': patient_json.get('date_of_birth', ''),
        'patient_gender': patient_json.get('gender', ''),
        'patient_address': patient_json.get('address', ''),
        'patient_state': patient_json.get('state', ''),
        'patient_city': patient_json.get('city', ''),
        'patient_zip': patient_json.get('zip_code', ''),
        'patient_number': patient_json.get('cell_phone').replace('(', '').replace(')', '') if len(patient_json.get('cell_phone')) == 14 else "000 000-0000",
        'patient_insured_relation': 'self', # HARD CODED
        'another_health_plan': '', # HARD CODED

        #Middle Section
        'signature': 'Signature on File', # HARD CODED
        'signature_date': appt_json['clinical_note'].get('updated_at'),

        #Bottom Section
        'icd_indicator': '0', # HARD CODED
        'icd10_codes': appt_json.get('icd10_codes'),
        'service_date': [],
        'code': [],
        'diagnosis_pointer': [],
        'charges': [],

        'service_place': '11', # HARD CODED
        'days_units': '1', # HARD CODED
        'provider_npi': '1326453796', # HARD CODED

        #Very bottom section (MOSTLY HARD CODED)
        'federal_id': '83-3726403',
        'SSN': 'false',
        'EIN': 'true',
        'patient_account_number': '511594374305555',
        'accept_assignment': 'true',
        'physician_signature': 'E. Kurokawa',
        'office': 'Primary Office',
        'provider_address': '4500 Satellite Blvd, Suite 1140',
        'provider_city_state': 'Duluth, GA 30096',
        'provider_number': '678 404-7643',
        'provider_info': 'Back Pain MD'
    }

    for item in line_item_json:
        data['service_date'].append(item.get('service_date'))
        data['code'].append(item.get('code'))
        data['diagnosis_pointer'].append(item.get('diagnosis_pointers'))
        data['charges'].append(item.get('price'))

    return data

from io import BytesIO
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

def generate_hcfa_bill(request, data: dict) -> BytesIO:
    """
    Input patient, appointment and line item dict, return filled hcfa bill in bytes, if exception return nothing and print message warning.
    """
    blank_pdf = 'pdf/static/HCFA.pdf'
    buffer = BytesIO()
    HCFA_SIZE = (620, 800)
    c = canvas.Canvas(buffer, pagesize= HCFA_SIZE)
    width, height = HCFA_SIZE
    
    # NOTES FOR SPACING EACH ROW IS SPACED 25 PIXELS

    # -- DRAW CHECKS --
    # Box 1 - Insurance Type
    c.drawString(345, height - 124, '✓')

    # Box 3 - Sex
    if data['patient_gender'] == "Male":
        c.drawString(324, height - 148, '✓')
    elif data['patient_gender'] == 'Female':
        c.drawString(360, height - 148, '✓')

    # Box 6 - PT relation to Insured
    c.drawString(259, height - 173, '✓')

    # Box 10 - Employment
    c.drawString(317, height - 269, '✓')

    # Auto Accident (TO BE IMPLEMENTED)
    """
    if data['auto_accident_check'] == 'true':
        c.drawString(274, height - 292, '✓')
    else:
        c.drawString(317, height - 292, '✓')
    """
    c.drawString(274, height - 292, '✓')

    # Other Accident
    c.drawString(317, height - 316, '✓')

    # Box 11 Sex
    if data['patient_gender'] == "Male":
        c.drawString(511, height - 268, '✓')
    elif data['patient_gender'] == 'Female':
        c.drawString(562, height - 268, '✓')

    # Another health benefit?
    c.drawString(432, height - 340, '✓')

    # SSN OR EIN
    c.drawString(159, height - 699, '✓')

    # Box 27 Accept Assignment
    c.drawString(296, height - 699, '✓')

    # -- DRAW TEXT --
    c.setFont("Courier", 10)  # Standard font/size for HCFA


    # Box 2 – Patient Name
    c.drawString(37, height - 146, data['patient_name'])

    # Box 3 - Patient DOB
    data['patient_dob'] = data['patient_dob'].split('-')
    c.drawString(247, height - 147, data['patient_dob'][1])
    c.drawString(270, height - 147, data['patient_dob'][2])
    c.drawString(290, height - 147, data['patient_dob'][0])

    # Box 4 - Insured Name
    c.drawString(388, height - 146, data['patient_name'])

    # Box 5 Patient Address
    c.drawString(37, height - 171, data['patient_address'])

    # City
    c.drawString(37, height - 194, data['patient_city'])
    
    # State
    c.drawString(211, height - 194, data['patient_state'])

    # Zipcode
    c.drawString(37, height - 219, data['patient_zip'])

    # Phone number
    data['patient_number'] = data['patient_number'].split(' ')
    c.drawString(134, height - 221, data['patient_number'][0])
    c.drawString(162, height - 221, data['patient_number'][1])

    # Box 7 Insured Address
    c.drawString(388, height - 170, data['patient_address'])

    # City
    c.drawString(388, height - 194, data['patient_city'])

    # State
    c.drawString(555, height - 194, data['patient_state'])

    # Zipcode
    c.drawString(388, height - 219, data['patient_zip'])

    # Phone Number
    c.drawString(493, height - 220, data['patient_number'][0])
    c.drawString(520, height - 220, data['patient_number'][1])

    # Box 11 Insured DOB
    c.drawString(407, height - 268, data['patient_dob'][1])
    c.drawString(430, height - 268, data['patient_dob'][2])
    c.drawString(450, height - 268, data['patient_dob'][0])

    # Box 12 Signature
    c.drawString(72, height - 385, data['signature'])

    # Date
    data['signature_date'] = data['signature_date'][:10].split('-')
    c.drawString(280, height - 385, data['signature_date'][1] + '/' + data['signature_date'][2] + '/' + data['signature_date'][0])
    
    # Box 13 Insured Signature
    c.drawString(430, height - 385, data['signature'])

    # Box 21 ICD10 CODES
    for i, code in enumerate(data['icd10_codes']):
        c.drawString(50 + (93 * i) - (373 * int(i / 4)), height - 484 - (12 * int(i / 4)), code)

    # ICD ind
    c.drawString(327, height - 474, data['icd_indicator'])

    # Box 24 Dates of Service
    for i, date in enumerate(data['service_date']):
        date = date.split('-')
        c.drawString(32, height - 555 - (i * 24), date[1])
        c.drawString(53, height - 555 - (i * 24), date[2])
        c.drawString(74, height - 555 - (i * 24), date[0][2:])
        c.drawString(95, height - 555 - (i * 24), date[1])
        c.drawString(116, height - 555 - (i * 24), date[2])
        c.drawString(139, height - 555 - (i * 24), date[0][2:])

    # Place of service. (SAME SERVICE PLACE HARD CODED JUST REPEAT PER CHARGE)
    for i in range(len(data['charges'])):
        c.drawString(161, height - 555 - (i * 24), data['service_place'])

    # Procedures
    for i, procedure in enumerate(data['code']):
        c.drawString(210, height - 555 - (i * 24), procedure)

    # Diagnosis Pointer. (SAME DIAGNOSIS POINTER HARD CODED JUST REPEAT PER CHARGE)
    for i in range(len(data['charges'])):
        c.drawString(355, height - 555 - (i * 24), 'a')
    
    # Charges
    for i, charge in enumerate(data['charges']):
        value = charge.split('.')
        c.drawString(387, height - 555 - (i * 24), value[0])
        c.drawString(427, height - 555 - (i * 24), value[1])

    # Days or units
    for i in range(len(data['charges'])):
        c.drawString(455, height - 555 - (i * 24), data['days_units'])

    # Provider NPI
    for i in range(len(data['charges'])):
        c.drawString(523, height - 555 - (i * 24), data['provider_npi'])

    # Box 25 Federal ID Number
    c.drawString(37, height - 698, data['federal_id'])

    # Box 26 Patient Account Number
    c.drawString(190, height - 698, data['patient_account_number'])

    # Box 28 Total Charge
    total_charge = 0
    for charge in data['charges']:
        total_charge += float(charge)
    total_charge = str(total_charge)
    total_charge = total_charge.split('.')

    c.drawString(390, height - 698, total_charge[0])
    c.drawString(443, height - 698, total_charge[1] if len(total_charge[1]) != 1 else f'{total_charge[1]}0')

    # Box 31 Provider Signature
    c.drawString(37, height - 745, data['physician_signature'])

    # Date
    c.drawString(120, height - 750, data['signature_date'][1] + '/' + data['signature_date'][2] + '/' + data['signature_date'][0])

    # Box 32 Provider Location
    c.drawString(190, height - 720, data['office'])
    c.drawString(190, height - 735, data['provider_address'])
    c.drawString(190, height - 745, data['provider_city_state'])

    # Box 33 Provider info
    data['provider_number'] = data['provider_number'].split(' ')
    c.drawString(500, height - 712, data['provider_number'][0])
    c.drawString(525, height - 712, data['provider_number'][1])
    c.drawString(388 , height - 720, data['provider_info'])
    c.drawString(388, height - 735, data['provider_address'])
    c.drawString(388, height - 745, data['provider_city_state'])

    # NPI
    c.drawString(388, height - 760, data['provider_npi'])

    c.save()
    buffer.seek(0)

    # Merge overlay with blank template
    template_pdf = PdfReader(blank_pdf)
    overlay_pdf = PdfReader(buffer)

    writer = PdfWriter()
    page = template_pdf.pages[0]
    page.merge_page(overlay_pdf.pages[0])
    writer.add_page(page)

    output = BytesIO()
    writer.write(output)
    output.seek(0)

    return output
