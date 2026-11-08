"""
qr/generate_qr_samples.py
─────────────────────────
Generates QR codes embedded with route, stop, and vehicle metadata
for passenger complaint reporting.

Usage:
    python qr/generate_qr_samples.py

Outputs:
    qr/sample_qr_bus_interior.png
    qr/sample_qr_bus_stop.png
"""

import os
from pathlib import Path
import qrcode
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
QR_DIR = ROOT / "qr"
QR_DIR.mkdir(parents=True, exist_ok=True)

BASE_FORM_URL = "https://forms.gle/DelhiTransitFeedback"

# Scenario 1: Inside a Bus
# Embedded URL carries: route_id=784 (774DOWN), vehicle_id=DL1PC9421
url_bus = f"{BASE_FORM_URL}?route=784&vehicle=DL1PC9421&source=bus_interior"

# Scenario 2: At a Bus Stop
# Embedded URL carries: stop_id=DEL0234, stop_name=Azadpur_Terminal
url_stop = f"{BASE_FORM_URL}?stop=DEL0234&name=Azadpur_Terminal&source=bus_shelter"

def make_qr_card(url: str, title: str, subtitle: str, filename: str):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#1a237e", back_color="white").convert("RGB")

    # Create a nice branded card image
    card_w = qr_img.width + 60
    card_h = qr_img.height + 120
    card = Image.new("RGB", (card_w, card_h), "#f8f9fa")
    draw = ImageDraw.Draw(card)

    # Header banner
    draw.rectangle([(0, 0), (card_w, 45)], fill="#1a237e")
    draw.text((15, 12), "TRACE • Delhi Bus Passenger Feedback", fill="white")

    # Paste QR code
    card.paste(qr_img, (30, 60))

    # Footer instructions
    draw.text((30, card_h - 45), title, fill="#0d47a1")
    draw.text((30, card_h - 25), subtitle, fill="#555555")

    out_path = QR_DIR / filename
    card.save(out_path)
    print(f"Generated QR card: {out_path.name} -> {url}")

if __name__ == "__main__":
    make_qr_card(
        url_bus,
        "SCAN TO REPORT DELAY / ISSUE",
        "Vehicle: DL1PC9421 • Route: 774DOWN",
        "sample_qr_bus_interior.png"
    )
    make_qr_card(
        url_stop,
        "SCAN TO REPORT BUS WAITING TIME",
        "Bus Stop: Azadpur Terminal (DEL0234)",
        "sample_qr_bus_stop.png"
    )
    print("QR generation complete.")
