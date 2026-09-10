import os
import django
from decimal import Decimal

import sys
sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'parking_management.settings')
django.setup()

from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
User = get_user_model()
from parking_zones.models import ParkingZone, Reservation
from django.core import signing

client = Client()
admin_user = User.objects.filter(is_staff=True).first()
if not admin_user:
    admin_user = User.objects.create_superuser('testadmin', 'testadmin@example.com', 'adminpass123')
client.force_login(admin_user)

zone = ParkingZone.objects.first()
print(f"Testing with zone: {zone.name} ({zone.slug})")

# 1. Virtual Gate GET request
resp = client.get(reverse('admin_virtual_gate'))
assert resp.status_code == 200, f"Virtual gate status code: {resp.status_code}"
content = resp.content.decode('utf-8')
assert 'id="vg-pass-actions-box"' in content, "vg-pass-actions-box MUST always be in DOM"
assert 'id="vg-pass"' in content, "vg-pass button MUST always be in DOM"
assert 'id="vg-view-btn-all"' in content, "vg-view-btn-all MUST be in DOM"
assert 'id="vg-view-btn-compact"' in content, "vg-view-btn-compact MUST be in DOM"
assert 'virtual-gate.js?v=2.2.3' in content, "Script version must be 2.2.3"
print("[OK] Virtual gate GET HTML has all required elements in DOM")

# 2. Walk-in ticket issue AJAX
walkin_resp = client.post(
    reverse('admin_virtual_gate'),
    {
        'action': 'walk_in_issue',
        'zone': zone.pk,
        'mode': 'entry',
        'walk_in_plate': '2AZ-8888',
        'idempotency_key': f'test_idemp_{timezone.now().timestamp()}',
    },
    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
    HTTP_ACCEPT='application/json',
)
assert walkin_resp.status_code == 200, f"Walk-in issue status: {walkin_resp.status_code}"
data = walkin_resp.json()
assert data.get('success') is True, "Walk-in ticket issue failed"
assert data.get('gate_open') is True, "Gate must be open for walk-in"
assert data.get('permit'), "Permit must be returned for walk-in"
ticket_code = data['ticket_code']
permit = data['permit']
print(f"[OK] Walk-in ticket issued: #{ticket_code}, gate_open=True, permit issued")

# 3. Confirm vehicle entry passage via AJAX
pass_resp = client.post(
    reverse('admin_virtual_gate'),
    {
        'action': 'pass',
        'zone': zone.pk,
        'mode': 'entry',
        'code': ticket_code,
        'permit': permit,
    },
    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
    HTTP_ACCEPT='application/json',
)
assert pass_resp.status_code == 200, f"Pass status: {pass_resp.status_code}"
pass_data = pass_resp.json()
assert pass_data.get('success') is True, "Pass confirmation failed"
assert pass_data.get('passed') is True, "Vehicle passage must be recorded"
assert pass_data.get('gate_open') is False, "Barrier must be closed after passage"
print(f"[OK] Vehicle entry passage confirmed for #{ticket_code}")

# 4. Exit test: Settle cash & test passage
res = Reservation.objects.get(ticket_code=ticket_code)
assert res.status == 'CHECKED_IN', f"Reservation status: {res.status}"

settle_resp = client.post(
    reverse('admin_virtual_gate'),
    {
        'action': 'settle',
        'zone': zone.pk,
        'mode': 'exit',
        'code': ticket_code,
        'payment_provider': 'CASH',
        'outcome': 'success',
    },
    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
    HTTP_ACCEPT='application/json',
)
assert settle_resp.status_code == 200, f"Settle status: {settle_resp.status_code}"
settle_data = settle_resp.json()
assert settle_data.get('settled') is True, "Exit balance must be settled"
assert settle_data.get('gate_open') is True, "Exit barrier must open on settlement"
exit_permit = settle_data['permit']
print(f"[OK] Exit balance settled: gate_open=True, exit_permit issued")

# 5. Confirm vehicle exit departure passage via AJAX
exit_pass_resp = client.post(
    reverse('admin_virtual_gate'),
    {
        'action': 'pass',
        'zone': zone.pk,
        'mode': 'exit',
        'code': ticket_code,
        'permit': exit_permit,
    },
    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
    HTTP_ACCEPT='application/json',
)
assert exit_pass_resp.status_code == 200, f"Exit pass status: {exit_pass_resp.status_code}"
exit_pass_data = exit_pass_resp.json()
assert exit_pass_data.get('success') is True, "Exit pass confirmation failed"
assert exit_pass_data.get('passed') is True, "Departure passage must be recorded"
assert exit_pass_data.get('gate_open') is False, "Exit barrier must be closed after departure"
print(f"[OK] Vehicle exit departure confirmed for #{ticket_code}")

# 6. Zone Detail Page (Pic 2)
zone_url = reverse('zone_detail', kwargs={'slug': zone.slug})
zone_resp = client.get(zone_url)
assert zone_resp.status_code == 200, f"Zone detail status: {zone_resp.status_code}"
zone_content = zone_resp.content.decode('utf-8')
assert 'position: -webkit-sticky !important;' in zone_content, "Sticky sidebar must be in status.html"
assert 'position: sticky !important;' in zone_content, "Sticky sidebar must be in status.html"
assert 'id="zone-detail-sidebar"' in zone_content, "zone-detail-sidebar must be in status.html"
assert 'style="height:100%; min-width:0; position:static;"' not in zone_content, "position:static inline must be removed"
print("[OK] Zone detail page has verified sticky sidebar styling")

# 7. CSS checks
with open('static/css/virtual-gate.css', 'r', encoding='utf-8') as f:
    css_content = f.read()
assert 'position: sticky;' in css_content, "sticky must be in virtual-gate.css"
assert '.vg-display-panel' in css_content, "vg-display-panel must be in virtual-gate.css"
assert '.vg-btn-pulse' in css_content, "vg-btn-pulse must be in virtual-gate.css"
assert '.vg-scene.is-compact' in css_content, "is-compact must be in virtual-gate.css"
print("[OK] virtual-gate.css has all required sticky, compact, and animation styles")

print("\n=== ALL VERIFICATION CHECKS PASSED SUCCESSFULLY! ===")
