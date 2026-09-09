# SomPark (ចំណតឆ្លាតវៃ រាជធានីភ្នំពេញ)
> Modern, High-Contrast Smart Parking Management System for Phnom Penh Capital.

SomPark transforms parking operations across Phnom Penh with real-time slot occupancy tracking, advance reservations, official Cambodian Riel (៛ / KHR) pricing, strict Cambodian plate/phone validation, atomic concurrency control, virtual gate boom barriers, in-app customer exit payment, and digital printable ticketing.

---

## 1. Teacher Quick Start (Windows PowerShell)

Follow these step-by-step instructions to set up and run SomPark using a local MySQL database on Windows.

### Prerequisites
- **Python**: 3.10, 3.11, 3.12, 3.13, or 3.14
- **MySQL Server**: 8.0+ (Standalone MySQL Community Server or XAMPP MySQL)
- Modern web browser (Chrome, Edge, Firefox)

---

### Step 1: Open PowerShell and Navigate to Project
```powershell
cd e:\Python\Parking-Slot-MGM
```

### Step 2: Create and Activate Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(If PowerShell restricts script execution, enable it for your current session using `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)*

### Step 3: Install Required Dependencies
```powershell
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy the template configuration to create your local `.env` file:
```powershell
Copy-Item .env.example .env
```

Open `.env` in your text editor and verify the **Local MySQL** settings:
```env
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=my_app_db
DB_USERNAME=root
DB_PASSWORD=secret
DB_CONN_MAX_AGE=60
```
- **Replace `secret`** with your actual local MySQL root password.
- If your local MySQL root user has **no password**, leave it empty: `DB_PASSWORD=`.
- If your password contains `#`, spaces, or special symbols, enclose it in double quotes: `DB_PASSWORD="p#ss word"`.
- **Local MySQL and SSL**: Local MySQL runs without a certificate. Ensure `MYSQL_SSL_CA` and `MYSQL_SSL_CA_PEM` are left empty or commented out.

---

### Step 5: Start Local MySQL Service
Ensure your local MySQL service is running:
```powershell
# For MySQL Windows Service (MySQL80 or similar):
Start-Service MySQL80

# Or if using XAMPP:
# Start MySQL from the XAMPP Control Panel
```

---

### Step 6: Create the Empty MySQL Database
> **Important**: The MySQL database must already exist before running migrations. Django creates the tables inside the database, but it does **not** create the MySQL database itself.

Open your MySQL client or run this command in PowerShell:
```powershell
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS my_app_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```
*(Omit `-p` if your root user does not have a password)*

---

### Step 7: Run System Checks, Migrations, and Seeding
Execute the setup commands in sequence:

```powershell
# 1. Verify configuration and system integrity
python manage.py check

# 2. Apply database migrations to create schema
python manage.py migrate

# 3. Seed Phnom Penh parking facilities and sample data (Idempotent)
python manage.py seed_demo

# 4. Create an interactive administrator account
python manage.py createsuperuser

# 5. Start the development server
python manage.py runserver
```

---

### Step 8: Access the Application

Once the server is running (`http://127.0.0.1:8000/`):

| Interface | URL | Description |
|---|---|---|
| **Public Portal & Booking** | `http://127.0.0.1:8000/` | Browse Phnom Penh zones, book parking, view live rates in KHR. |
| **Customer My Tickets** | `http://127.0.0.1:8000/ticket/` | View ticket pass, scannable access QR, countdowns, exit payment. |
| **Virtual Parking Gate** | `http://127.0.0.1:8000/admin/virtual-gate/` | Gate operator barrier simulation (Camera QR scanning, entry/exit). |
| **Operations Workbench** | `http://127.0.0.1:8000/staff/dashboard/` | Staff real-time occupancy monitor and manual ticket lookups. |
| **Django Admin** | `http://127.0.0.1:8000/admin/` | Manage zones, reservations, users, and audit logs. |

---

## 2. Seeded Demo Accounts & Sample Data

The `python manage.py seed_demo` command is **fully idempotent**:
- It can be executed repeatedly on existing or fresh databases without creating duplicate records.
- It **never resets** existing passwords, reservations, payments, or live occupancy counts.
- It **never deletes** any records.

### Sample Customer Account
- **Username**: `demo`
- **Password**: `password123`
- **Role**: Registered Commuter with 3 pre-seeded sample tickets:
  1. `SPK-DEMO001`: **CONFIRMED** unpaid hold with active 3-hour arrival window.
  2. `SPK-DEMO002`: **CHECKED_IN** active parked vehicle with first-day deposit paid.
  3. `SPK-DEMO003`: **CHECKED_OUT** completed historical stay with receipt.

---

## 3. Background Services & Payment Modes

### Reservation Expiry Worker
SomPark includes a management command to release stale unpaid holds, timed-out deposit checkouts, and no-shows:
```powershell
python manage.py expire_reservations
```
In production, schedule this command via Windows Task Scheduler or cron to run every 1–5 minutes.

### Payment Integration: Demo vs. Real Gateways
- **Demo Mode (`DEMO_PAYMENT_ENABLED=True`)**: Provides a verified, server-side simulated payment adapter for Bakong KHQR and exit balances. It allows testing payment confirmations, failures, cancellations, and duplicate prevention without actual banking credentials.
- **Production Banking**: To connect real Bakong KHQR (National Bank of Cambodia) or commercial acquirers (e.g. ABA PayWay), configure live merchant API credentials in `.env`.

---

## 4. Database Precedence & Configuration Reference

SomPark resolves its database configuration with explicit 3-tier precedence:

1. **Tier 1 (Highest)**: If `DB_CONNECTION` is non-empty (`DB_CONNECTION=mysql`), SomPark uses the separate `DB_*` variables (`DB_HOST`, `DB_PORT`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD`).
2. **Tier 2**: If `DB_CONNECTION` is unset and `DATABASE_URL` is configured, SomPark parses `DATABASE_URL` (used for cloud deployments such as Aiven MySQL).
3. **Tier 3 (Fallback)**: If neither is set, SomPark safely falls back to a local SQLite database (`db.sqlite3`).

### Environment Variables Matrix
| Variable | Required for Local MySQL | Default | Description |
|---|---|---|---|
| `DB_CONNECTION` | **Yes** | — | Database engine (`mysql` or `sqlite`). Takes precedence over `DATABASE_URL`. |
| `DB_HOST` | **Yes** | `127.0.0.1` | Local MySQL server host. |
| `DB_PORT` | No | `3306` | MySQL TCP port (1–65535). |
| `DB_DATABASE` | **Yes** | — | Target MySQL database name (e.g. `my_app_db`). |
| `DB_USERNAME` | **Yes** | — | Database user (e.g. `root`). |
| `DB_PASSWORD` | No | `""` | Database user password. Enclose in quotes if containing `#` or spaces. |
| `DB_CONN_MAX_AGE` | No | `60` | Persistent connection age in seconds. |
| `MYSQL_SSL_CA` | No (Cloud only) | `""` | Path to SSL CA certificate (leave empty for local MySQL). |
| `MYSQL_SSL_CA_PEM` | No (Cloud only) | `""` | Raw PEM certificate content (leave empty for local MySQL). |

---

## 5. Troubleshooting Common Setup Issues

### 1. `Can't connect to MySQL server on '127.0.0.1'`
- **Cause**: MySQL service is stopped or listening on a different port.
- **Fix**: Check service status with `Get-Service MySQL*` in PowerShell. Run `Start-Service MySQL80` or launch MySQL via XAMPP Control Panel. Confirm port 3306 is open: `Test-NetConnection -ComputerName 127.0.0.1 -Port 3306`.

### 2. `Access denied for user 'root'@'localhost'`
- **Cause**: Incorrect password in `.env`.
- **Fix**: Verify your password by testing `mysql -u root -p`. Update `DB_PASSWORD` in `.env`. If your password has `#`, spaces, or special characters, wrap it in double quotes (e.g. `DB_PASSWORD="my#secret"`).

### 3. `Unknown database 'my_app_db'`
- **Cause**: The MySQL database has not been created yet.
- **Fix**: Connect to MySQL and create it:
  ```sql
  CREATE DATABASE my_app_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  ```

### 4. `SSL connection error: unknown error number` or SSL handshake failures
- **Cause**: Leftover Aiven SSL certificate settings in local configuration.
- **Fix**: Local MySQL does not use SSL certificates. Ensure `MYSQL_SSL_CA` and `MYSQL_SSL_CA_PEM` in `.env` are empty or commented out.

### 5. `ModuleNotFoundError: No module named 'pymysql'` or `'dotenv'`
- **Cause**: Virtual environment is not activated or dependencies were not installed.
- **Fix**: Activate virtual environment (`.\venv\Scripts\Activate.ps1`) and run `pip install -r requirements.txt`.

---

## 6. Running the Automated Test Suite

To run all automated test suites safely against the test database:
```powershell
python manage.py test --keepdb
```
The test suite validates:
- In-app exit payment lifecycle and customer authorization
- Virtual gate barrier simulation and scannable QR verification
- Concurrency control and single capacity release invariants
- Database configuration precedence and credential safety
