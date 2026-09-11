<div align="center">

# SomPark

### Smart, high-contrast parking management for Phnom Penh Capital.

Transform parking operations across Phnom Penh with real-time slot occupancy tracking, walk-in ticketing with barrier simulation, advance reservations, official Cambodian Riel (៛ / KHR) pricing, strict Cambodian plate validation, and digital printable ticketing.

[![DJANGO](https://img.shields.io/badge/DJANGO-5.2%20LTS-092E20?style=flat-square&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![PYTHON](https://img.shields.io/badge/PYTHON-3.10%20%7C%203.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![DATABASE](https://img.shields.io/badge/DATABASE-MYSQL%208.0%2B-4479A1?style=flat-square&logo=mysql&logoColor=white)](https://www.mysql.com/)
[![PAYMENTS](https://img.shields.io/badge/PAYMENTS-BAKONG%20KHQR-E01E26?style=flat-square)](https://bakong.nbc.gov.kh/)
[![CURRENCY](https://img.shields.io/badge/CURRENCY-KHR%20(%E1%9F%9B)-F59E0B?style=flat-square)](https://www.nbc.gov.kh/)
[![GEMINI AI](https://img.shields.io/badge/GEMINI%20AI-TOGGLEABLE-8E75FF?style=flat-square&logo=google-gemini&logoColor=white)](https://ai.google.dev/)

[Features](#features) · [Portals](#live-portals) · [Gate Simulator](#virtual-gate-simulator) · [Quick Start](#quick-start-windows-powershell) · [Billing Rules](#billing-rules) · [AI Assistant](#gemini-ai-assistant) · [Testing](#automated-testing)

</div>

---

> Phnom Penh has rapid motorization, busy commercial boulevards, and scarce curbside parking. SomPark gives drivers and operators real-time vacancy tracking, zero-oversell booking guarantees, and contactless gate telemetry.

---

## Features

| 🚗 Walk-In & Gate | 📱 Reservations & Commuters | ⚙️ Core Engine & Compliance |
|---|---|---|
| 🎫 Instant walk-in ticket dispenser | 📅 Advance spot booking up to 7 days | 🚧 Dual-mode virtual boom barrier |
| 🖨️ Printable thermal QR receipts | 💳 In-app exit settlement (KHQR / Cash) | 🚗 Animated drive-through simulation |
| 🕒 24-hour daily block billing | ⏳ Dynamic arrival countdown timers | 🔒 ACID row-locking (`select_for_update`) |
| 🚫 Zero overstay penalties for walk-ins | 🗺️ Interactive Google Maps explorer | 🇰🇭 Strict Cambodian plate & phone regex |
| 🏷️ Configurable per-facility rates | 📱 Cryptographic QR mobile pass | 🤖 Toggleable Gemini AI assistant |

Every parking facility in SomPark maintains its own live capacity, walk-in pricing, operational hours, active reservations, and telemetry logs. Data stays synchronized between physical drive-throughs and customer mobile passes in real time.

---

## Live Portals

Once the local server is running at `http://127.0.0.1:8000/`, access the primary interfaces:

| Portal | Route | Primary Role | Description |
|---|---|---|---|
| **Public Portal & Finder** | [`/`](http://127.0.0.1:8000/) | Public / Commuter | Interactive district map, live vacant spots, rates in KHR, and booking engine. |
| **Customer My Tickets** | [`/ticket/`](http://127.0.0.1:8000/ticket/) | Commuter | Active reservations, digital QR access pass, arrival countdowns, and exit payment. |
| **Virtual Parking Gate** | [`/admin/virtual-gate/`](http://127.0.0.1:8000/admin/virtual-gate/) | Gate Operator | Dual-mode simulator (Walk-in dispenser, camera QR scanner, boom barrier, vehicle animation). |
| **Operations Workbench** | [`/staff/dashboard/`](http://127.0.0.1:8000/staff/dashboard/) | Staff / Attendant | Facility occupancy telemetry, rapid ticket search, and real-time vehicle ledger. |
| **Django Administration** | [`/admin/`](http://127.0.0.1:8000/admin/) | Administrator | Full database management, facility pricing, user accounts, and audit logs. |

---

## Virtual Gate Simulator

The **Virtual Gate Simulator** (`/admin/virtual-gate/`) provides a full physical barrier terminal experience with sticky telemetry HUD and vehicle drive-through animations:

### Entrance Mode
1. **Walk-In Ticket Dispenser**:
   - Operator selects **Entrance Mode** and clicks **"Get walk-in ticket"**.
   - Review and accept the daily walk-in rate confirmation modal (e.g. `7,000 ៛/day`).
   - SomPark performs atomic capacity check: guarantees slots are available without violating reserved holds.
   - Generates thermal printable QR ticket modal with ticket code (e.g. `SPK-W...`) and rate snapshot.
2. **Barrier & Vehicle Passage**:
   - Barrier arm lifts automatically: **"BARRIER OPEN — WAITING FOR VEHICLE"**.
   - The glowing green button **"🚗 Confirm Vehicle Entry & Close Barrier (ឡានចូលរួច)"** lights up.
   - Clicking it triggers an upward vehicle drive-through animation, lowers the barrier arm smoothly, and starts the parking clock (`checked_in_at = now`).

### Exit Mode
1. **Ticket Lookup & Itemized Billing**:
   - Operator switches to **Exit Mode** and inputs or scans the ticket QR code.
   - The system displays the real-time itemized bill (24-hour block calculations for walk-ins; reserved days + overstay for app bookings).
2. **Payment & Barrier Clearance**:
   - Settle payment via **Cash** or **Demo ABA KHQR**.
   - Upon settlement, the barrier arm immediately lifts and the departure button appears.
   - Clicking **"🚗 Confirm Vehicle Departure & Close Barrier (ឡានចេញរួច)"** triggers a downward vehicle departure animation, closes the barrier, and atomically decrements physical occupancy.

---

## Billing Rules

SomPark strictly isolates walk-in ticketing from advance app bookings to prevent unfair penalties:

| Billing Dimension | 🚗 Walk-In Parking | 📱 Advance App Reservation |
|---|---|---|
| **Rate Basis** | Facility Walk-in Rate (`walk_in_price`, default `7,000 ៛/day`). | Facility Base Rate (`price`, e.g. `3,000 – 4,000 ៛/day`). |
| **Billing Increment** | Strict 24-hour calendar blocks from physical gate entry. | Pre-booked duration (`reserved_days`) chosen by customer. |
| **Minimum Charge** | **1 full day minimum** once vehicle crosses the barrier. | **1 full day** (deposit paid at booking or on arrival). |
| **Unentered Hold Charge**| **0 KHR** (holds auto-expire; no charge if vehicle never enters). | **0 KHR** for pay-later; deposit refunded if cancelled in time. |
| **Overstay Multiplier** | **None** (`1.0x` standard daily rate for each new 24h block). | **2.0x Multiplier** applied after reserved duration expires. |
| **Billing Label** | Clearly itemized as **`"Walk-in rate"`** on receipts. | Itemized as **`"Base Rate"`** + **`"Overstay Penalty"`**. |

---

## Gemini AI Assistant

SomPark includes an intelligent conversational assistant fluent in Khmer and English to help drivers find parking by district, price, and operating hours.

### Instant Environment Toggle (`gemini_ai=false`)
You have full control over the AI assistant via your `.env` file:

```env
# Disable Gemini AI: Hides UI card from homepage & blocks direct API access with HTTP 403
gemini_ai=false

# Re-enable Gemini AI:
gemini_ai=true
```

- **Clean UI**: When `gemini_ai=false`, the `#ai-assistant-section` and client scripts are omitted completely from the rendered DOM.
- **Backend Guard**: Direct calls to `/api/ai-assistant/` return HTTP 403 `{"error": "AI Assistant is currently disabled.", "code": "AI_ASSISTANT_DISABLED"}`.
- **Data Privacy**: Customer phone numbers, license plates, and cryptographic QR tokens are permanently scrubbed before any prompt reaches the model.

---

## Quick Start (Windows PowerShell)

Follow these step-by-step instructions to set up and run SomPark using a local MySQL database on Windows:

### 1. Open PowerShell and Navigate to Project
```powershell
cd e:\Python\Parking-Slot-MGM
```

### 2. Create and Activate Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(If PowerShell blocks script execution, run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)*

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the template configuration to create your local `.env`:
```powershell
Copy-Item .env.example .env
```

Generate a private Django cryptographic key:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Paste this string into `SECRET_KEY=` in `.env`.

Verify your **Local MySQL** settings in `.env`:
```env
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=my_app_db
DB_USERNAME=root
DB_PASSWORD=secret
DB_CONN_MAX_AGE=60
```
- Replace `secret` with your local MySQL password (or leave empty `DB_PASSWORD=` if none).
- If your password contains `#`, special characters, or spaces, enclose it in quotes: `DB_PASSWORD="p#ss word"`.
- Keep `MYSQL_SSL_CA` empty for local MySQL.

### 5. Create MySQL Database
Ensure MySQL service is running, then run:
```powershell
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS my_app_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 6. Run Migrations, Seeder, and Start Server
```powershell
# 1. Validate configuration
python manage.py check

# 2. Apply database migrations
python manage.py migrate

# 3. Seed Phnom Penh parking facilities and sample data (Idempotent)
python manage.py seed_demo

# 4. Create administrator account
python manage.py createsuperuser

# 5. Start development server
python manage.py runserver
```

Open your browser at **`http://127.0.0.1:8000/`** to explore SomPark!

---

## Demo Accounts & Test Credentials

The `python manage.py seed_demo` command is **idempotent** — safe to run anytime without overwriting or resetting user records:

| Role | Username | Password | Pre-seeded Context |
|---|---|---|---|
| **System Administrator** | `admin` | *(Created via createsuperuser)* | Access to `/admin/` and `/admin/virtual-gate/`. |
| **Registered Customer** | `demo` | `password123` | Commuter with 3 pre-seeded sample tickets in `/ticket/`. |
| **Sample Ticket 1** | `SPK-DEMO001` | — | **CONFIRMED**: Unpaid advance hold with active 3-hour arrival deadline. |
| **Sample Ticket 2** | `SPK-DEMO002` | — | **CHECKED_IN**: Active parked vehicle in BKK1 with deposit paid. |
| **Sample Ticket 3** | `SPK-DEMO003` | — | **CHECKED_OUT**: Completed historical stay with itemized bill. |

---

## Environment Configuration (.env)

| Category | Variable | Required | Default | Description |
|---|---|---|---|---|
| **Django** | `DEBUG` | No | `True` | Set to `False` for production deployments. |
| | `NODE_ENV` | No | `development` | Hosting-mode hint. Set to `production` when publishing; Django security behavior is controlled by `DEBUG`. |
| | `PORT` | No | `3000` | Port used by `run.sh`; managed platforms may inject this automatically. |
| | `SECRET_KEY` | **Yes** | — | Cryptographic secret for signing tokens and sessions. |
| | `ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Comma-separated allowed hostnames. |
| **Database** | `DB_CONNECTION` | No | `sqlite` | Set `mysql` for local/cloud MySQL; unset for SQLite fallback. |
| | `DB_HOST` | If MySQL | `127.0.0.1` | Hostname/IP of MySQL database server. |
| | `DB_PORT` | No | `3306` | MySQL TCP port. |
| | `DB_DATABASE` | If MySQL | `my_app_db` | Target database name. |
| | `DB_USERNAME` | If MySQL | `root` | Database username. |
| | `DB_PASSWORD` | No | `""` | Database password (enclose in quotes if special characters). |
| | `DATABASE_URL` | No | — | Cloud MySQL URI (e.g. Aiven MySQL with SSL). |
| **AI & Feature Flags** | `gemini_ai` / `GEMINI_AI` | No | `true` | Set `false` to hide assistant UI card and disable API. |
| | `GEMINI_API_KEY` | Optional | `""` | Google Gemini API key (server-side only). |
| | `GOOGLE_MAPS_API_KEY` | Optional | `""` | Client-side Google Maps JavaScript API key. |
| **Payment & Holds** | `DEMO_PAYMENT_ENABLED` | No | `True` | Enables interactive Bakong KHQR and ABA demo simulators. |
| | `ARRIVAL_HOLD_HOURS` | No | `3` | Arrival window in hours for "Pay when you leave" holds. |
| | `DEPOSIT_ARRIVAL_HOLD_HOURS`| No | `5` | Arrival window in hours after first-day deposit is paid. |
| | `DEFAULT_OVERSTAY_MULTIPLIER`| No | `2.0` | Overstay multiplier applied after app booking expires. |

---

## Automated Testing

SomPark includes an automated regression test suite:

```powershell
# Run the complete test suite
python manage.py test --keepdb

# Target specific modules
python manage.py test --keepdb parking_zones.test_gemini_backend
python manage.py test --keepdb parking_zones.test_gemini_env_flag
python manage.py test --keepdb parking_zones.test_gate_machine
python manage.py test --keepdb parking_zones.test_walk_in_parking
python manage.py test --keepdb parking_zones.test_customer_checkout_enforcement
```

---

<div align="center">

**SomPark (ចំណតឆ្លាតវៃ រាជធានីភ្នំពេញ)** • *Crafted with ❤️ for Phnom Penh Capital*

</div>
