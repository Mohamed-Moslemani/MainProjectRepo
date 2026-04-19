"""Generate passport application PDF pre-filled with citizen data.

The generated form is what the mukhtar reviews and digitally stamps.
It contains the citizen's declared fields, verification results, and
a unique case tracking ID for traceability.
"""

import os
import logging
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from ..config import get_settings

logger = logging.getLogger(__name__)

LEBANON_GREEN = HexColor("#00A651")
LEBANON_RED = HexColor("#ED1C24")
HEADER_BG = HexColor("#F0F7F0")


def _get_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "FormTitle",
        parent=styles["Title"],
        fontSize=18,
        textColor=LEBANON_GREEN,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "FormSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        alignment=TA_CENTER,
        textColor=HexColor("#666666"),
        spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=LEBANON_GREEN,
        spaceBefore=14,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "FieldLabel",
        parent=styles["Normal"],
        fontSize=9,
        textColor=HexColor("#888888"),
    ))
    styles.add(ParagraphStyle(
        "FieldValue",
        parent=styles["Normal"],
        fontSize=11,
        spaceBefore=2,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=HexColor("#999999"),
        alignment=TA_CENTER,
    ))
    return styles


def _field_row(label: str, value: str, styles) -> list:
    return [
        Paragraph(label, styles["FieldLabel"]),
        Paragraph(str(value or "N/A"), styles["FieldValue"]),
    ]


def generate_passport_application(case, applicant) -> str:
    """Generate a passport application PDF and return the file path."""
    settings = get_settings()
    forms_dir = os.path.join(settings.upload_dir, "forms")
    os.makedirs(forms_dir, exist_ok=True)

    filename = f"passport_application_{case.tracking_id}.pdf"
    filepath = os.path.join(forms_dir, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = _get_styles()
    elements = []

    # --- Header ---
    elements.append(Paragraph("Lebanese Republic", styles["FormSubtitle"]))
    elements.append(Paragraph("Passport Application Form", styles["FormTitle"]))
    elements.append(Paragraph(
        f"Tracking ID: {case.tracking_id} | Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        styles["FormSubtitle"],
    ))
    elements.append(HRFlowable(width="100%", thickness=2, color=LEBANON_GREEN))
    elements.append(Spacer(1, 12))

    # --- Service Info ---
    service_labels = {
        "passport_new": "New Passport Application",
        "passport_renewal": "Passport Renewal Application",
    }
    elements.append(Paragraph(
        f"Service: {service_labels.get(case.service_type, case.service_type)}",
        styles["SectionHeader"],
    ))

    # --- Applicant Information ---
    elements.append(Paragraph("Applicant Information", styles["SectionHeader"]))

    declared = case.declared_fields or {}
    applicant_fields = [
        ("Full Name", declared.get("full_name") or applicant.full_name),
        ("Father's Name", declared.get("father_name") or applicant.father_name),
        ("Mother's Name", declared.get("mother_name") or applicant.mother_name),
        ("Date of Birth", declared.get("date_of_birth") or str(applicant.date_of_birth or "")),
        ("Place of Birth", declared.get("place_of_birth") or applicant.place_of_birth),
        ("Gender", declared.get("gender") or applicant.gender),
        ("Marital Status", declared.get("marital_status") or applicant.marital_status),
    ]

    table_data = [_field_row(label, value, styles) for label, value in applicant_fields]
    table = Table(table_data, colWidths=[5 * cm, 12 * cm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor("#E0E0E0")),
    ]))
    elements.append(table)

    # --- Civil Registry ---
    elements.append(Paragraph("Civil Registry Details", styles["SectionHeader"]))

    registry_fields = [
        ("Registry Number", declared.get("registry_number") or applicant.registry_number),
        ("Registry Place", declared.get("registry_place") or applicant.registry_place),
        ("Phone", applicant.phone),
        ("Address", applicant.address),
    ]

    table_data = [_field_row(label, value, styles) for label, value in registry_fields]
    table = Table(table_data, colWidths=[5 * cm, 12 * cm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor("#E0E0E0")),
    ]))
    elements.append(table)

    # --- Passport Details (renewal) ---
    if case.service_type == "passport_renewal":
        elements.append(Paragraph("Previous Passport Details", styles["SectionHeader"]))
        passport_fields = [
            ("Old Passport Number", declared.get("old_passport_number", "N/A")),
            ("Passport Type", declared.get("passport_type", "Regular")),
        ]
        table_data = [_field_row(label, value, styles) for label, value in passport_fields]
        table = Table(table_data, colWidths=[5 * cm, 12 * cm])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor("#E0E0E0")),
        ]))
        elements.append(table)

    # --- Verification Summary ---
    elements.append(Paragraph("System Verification Summary", styles["SectionHeader"]))

    risk = case.risk_result or {}
    recon = case.reconciliation_result or {}
    verification_fields = [
        ("Risk Score", f"{risk.get('risk_score', 'N/A')} / 100"),
        ("Risk Routing", risk.get("routing", "N/A")),
        ("Data Integrity", f"{recon.get('integrity_score', 'N/A')}"),
        ("Identity Verified", "Yes (Face + Liveness)" if case.liveness_result else "Pending"),
    ]

    table_data = [_field_row(label, value, styles) for label, value in verification_fields]
    table = Table(table_data, colWidths=[5 * cm, 12 * cm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor("#E0E0E0")),
        ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
    ]))
    elements.append(table)

    # --- Mukhtar Approval Section ---
    elements.append(Spacer(1, 24))
    elements.append(HRFlowable(width="100%", thickness=1, color=LEBANON_GREEN))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Mukhtar Certification", styles["SectionHeader"]))
    elements.append(Paragraph(
        "I, the undersigned Mukhtar, hereby certify that I have verified the identity "
        "of the above-named applicant and confirm the accuracy of the information provided.",
        styles["FieldValue"],
    ))
    elements.append(Spacer(1, 24))

    # Signature placeholders
    sig_data = [
        [Paragraph("Mukhtar Name: ___________________", styles["FieldValue"]),
         Paragraph("Date: ___________________", styles["FieldValue"])],
        [Paragraph("Digital Stamp: [PENDING]", styles["FieldValue"]),
         Paragraph("Signature: ___________________", styles["FieldValue"])],
    ]
    sig_table = Table(sig_data, colWidths=[8.5 * cm, 8.5 * cm])
    sig_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(sig_table)

    # --- Footer ---
    elements.append(Spacer(1, 24))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#CCCCCC")))
    elements.append(Paragraph(
        f"DocFlow Lebanon - Digital Passport Application | Case {case.tracking_id} | "
        "This document is system-generated and requires Mukhtar digital approval.",
        styles["Footer"],
    ))

    doc.build(elements)
    logger.info(f"Generated passport application form: {filepath}")
    return filepath