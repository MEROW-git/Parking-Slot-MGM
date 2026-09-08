# SomPark (ចំណតឆ្លាតវៃ រាជធានីភ្នំពេញ)
> Modern, High-Contrast Smart Parking Management System for Phnom Penh Capital.

SomPark transforms parking operations across Phnom Penh with real-time slot occupancy tracking, advance reservations, official Cambodian Riel (៛ / KHR) pricing, strict Cambodian plate/phone validation, atomic concurrency control, and digital printable ticketing.

---

## 1. Quick Start Guide

### Prerequisites
- **Python**: 3.11, 3.12, 3.13, or 3.14
- **SQLite3** (standard with Python)
- Modern web browser

### Windows (PowerShell) Setup
```powershell
# 1. Clone & enter project repository
cd parking-management

# 2. Create and activate a Python virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
Copy-Item .env.example .env

# 5. Run migrations (seeds realistic Phnom Penh zones automatically)
python manage.py migrate

# 6. Run automated test suite
python manage.py test

# 7. Start the development server
python manage.py runserver 3000
```

### macOS / Linux / Bash Setup
```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env

# 4. Run database migrations
python3 manage.py migrate

# 5. Run test suite
python3 manage.py test

# 6. Start server
python3 manage.py runserver 3000
```

---

## 2. Instant Demo Credentials

For testing and rapid evaluation:
- **Username**: `demo`
- **Password**: `password123`
- **Role**: Registered Commuter (can make reservations, view tickets, and check out)

Admin access can be created using:
```bash
python manage.py createsuperuser
```

---

## 3. Architecture & Core Innovations

### Concurrency & Slot Integrity
- **Atomic Operations**: All booking and check-out workflows execute within `transaction.atomic()` blocks.
- **Pessimistic Row-Locking**: In booking views, `ParkingZone.objects.select_for_update()` ensures zero race conditions or overbooking even during high concurrent traffic spikes.
- **Invariant Guarantees**: Model-level validation ensures slot counts cannot become negative, cannot exceed total lot capacity, and synchronize cleanly between `occupied_slots` and `vacant_slots`.
- **POST-Only Checkout**: Prevents accidental or CSRF-based reservation cancellation from web crawlers or GET link clicks.

### Cambodia-Specific Localization
- **Currency**: Transparent pricing displayed in Cambodian Riel (`៛ / KHR`), e.g., `3,000 ៛ / day`.
- **Phone Number Validation**: Strictly enforces Cambodian mobile patterns (`+855` country code or `0XX` national format, 8-10 digits).
- **Vehicle Plate Validation**: Enforces Cambodian vehicle registration formats (e.g., `2AZ-1234`, `Phnom Penh 2BC-5678`, `1A-9999`).
- **Phnom Penh Districts**: Seeded with real locations across Riverside (Sisowath Quay), BKK1, Toul Kork, Sen Sok, Olympic Stadium, and Vattanac/Canadia Financial Center.

### Dependable Print Tickets
- Replaced fragile PDF rendering libraries with a dependable, browser-native printable HTML ticket (`@media print` stylesheet) formatted with official receipt barcodes, facility addresses, plate numbers, and customer contact information.

---

## 4. Reusable Component System

Templates are organized modularly under `templates/components/`:
- `navigation.html`: Sticky header with brand badge, responsive layout, auth states, and mobile menu trigger.
- `parking_zone_item.html`: Expressive zone card showing live occupancy status, price in KHR, and direct booking actions.
- `availability_indicator.html`: Color-coded status badge (`Available`, `Limited`, `Full`).
- `reservation_summary.html`: Real-time banner displaying active parking ticket and instant check-out trigger.
- `form_field.html`: High-contrast form control with integrated labels, asterisks, help notes, and inline validation errors.
- `alert.html`: System flash messages for errors, warnings, success, and notices.
- `button.html`: Consistent geometric button styles (`primary`, `secondary`, `dark`, `destructive`, `sm`).
- `empty_state.html`: Distinctive zero-data states with contextual call-to-action buttons.
- `page_header.html`: Standardized editorial headers with Khmer subtitles.
- `footer.html`: Government initiative branding, hotline contacts, and district links.

Live visual documentation of all components is available at `/components/`.

---

## 5. Automated Test Coverage

The test suite covers 21 test cases across models, forms, security, and views:
```bash
python manage.py test
```
- Model occupancy invariants and atomic increment/decrement limits
- Phone and plate format regex validation
- Booking authentication enforcement
- Prevention of duplicate active bookings
- Full capacity rejection
- Ticket code generation
- Checkout authorization (preventing non-owners from checking out other users' tickets)
- Authentication flows (login, invalid password handling, signup, and logout)
