import bcrypt from 'bcryptjs';
import crypto from 'crypto';
import mysql from 'mysql2/promise';
import MySQLStoreFactory from 'express-mysql-session';

type Pool = mysql.Pool;

export interface User {
  id: string;
  username: string;
  passwordHash: string;
}

export interface ParkingZone {
  id: string;
  name: string;
  khmer_name: string;
  slug: string;
  num_of_slots: number;
  occupied_slots: number;
  vacant_slots: number;
  address: string;
  district: string;
  price: number;
  operating_hours: string;
  description: string;
}

export interface ParkingZoneView extends ParkingZone {
  price_khr_formatted: string;
  is_full: boolean;
  is_nearly_full: boolean;
  availability_status: 'full' | 'limited' | 'available';
  occupancy_percentage: number;
}

export interface Reservation {
  id: string;
  ticket_code: string;
  customer: string; // username
  start_date: string;
  finish_date: string;
  parking_zone: string; // zone name
  parking_zone_slug?: string;
  plate_number: string;
  phone_number: string;
  checked_out: boolean;
  created_on: string;
}

export function generateTicketCode(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let suffix = '';
  for (let i = 0; i < 7; i++) {
    suffix += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return `SPK-${suffix}`;
}

export function toZoneView(zone: ParkingZone): ParkingZoneView {
  const is_full = zone.vacant_slots <= 0;
  const is_nearly_full =
    !is_full && zone.vacant_slots <= Math.max(3, Math.floor(zone.num_of_slots * 0.15));
  const availability_status: 'full' | 'limited' | 'available' = is_full
    ? 'full'
    : is_nearly_full
    ? 'limited'
    : 'available';
  const occupancy_percentage = zone.num_of_slots
    ? Math.round((zone.occupied_slots / zone.num_of_slots) * 100)
    : 0;

  return {
    ...zone,
    price_khr_formatted: `${zone.price.toLocaleString()} ៛`,
    is_full,
    is_nearly_full,
    availability_status,
    occupancy_percentage,
  };
}

// Generates Django-compatible pbkdf2_sha256 password hash
export function hashPassword(plainText: string): string {
  const salt = crypto.randomBytes(12).toString('base64');
  const iter = 100000;
  const hash = crypto.pbkdf2Sync(plainText, salt, iter, 32, 'sha256').toString('base64');
  return `pbkdf2_sha256$${iter}$${salt}$${hash}`;
}

// Verifies Django pbkdf2_sha256, bcrypt, or plain passwords
export function verifyPassword(plainText: string, storedHash: string): boolean {
  if (!storedHash || !plainText) return false;

  if (storedHash.startsWith('pbkdf2_sha256$')) {
    const parts = storedHash.split('$');
    if (parts.length === 4) {
      const iter = parseInt(parts[1], 10);
      const salt = parts[2];
      const expected = parts[3];
      const derived = crypto.pbkdf2Sync(plainText, salt, iter, 32, 'sha256').toString('base64');
      return derived === expected;
    }
  }

  if (
    storedHash.startsWith('$2a$') ||
    storedHash.startsWith('$2b$') ||
    storedHash.startsWith('$2y$')
  ) {
    try {
      return bcrypt.compareSync(plainText, storedHash);
    } catch {
      return false;
    }
  }

  return plainText === storedHash;
}

function getDatabaseConfig() {
  let dbUrl = process.env.DATABASE_URL?.trim();
  if (!dbUrl && process.env.DB_CONNECTION === 'mysql' && process.env.DB_HOST) {
    const user = encodeURIComponent(process.env.DB_USERNAME || 'root');
    const pass = encodeURIComponent(process.env.DB_PASSWORD || '');
    const host = process.env.DB_HOST;
    const port = process.env.DB_PORT || '3306';
    const db = process.env.DB_DATABASE || 'defaultdb';
    dbUrl = `mysql://${user}:${pass}@${host}:${port}/${db}`;
  }

  if (!dbUrl) return null;

  if (dbUrl.startsWith('mysql+pymysql://')) {
    dbUrl = 'mysql://' + dbUrl.slice('mysql+pymysql://'.length);
  }

  try {
    const url = new URL(dbUrl);
    let ca = process.env.MYSQL_SSL_CA_PEM || process.env.MYSQL_SSL_CA;
    if (ca && ca.includes('\\n')) {
      ca = ca.replace(/\\n/g, '\n');
    }

    const isAiven = url.hostname.includes('aivencloud.com');
    const ssl = ca
      ? { ca, rejectUnauthorized: false }
      : isAiven
      ? { rejectUnauthorized: false }
      : undefined;

    return {
      host: url.hostname,
      port: parseInt(url.port || '3306', 10),
      user: decodeURIComponent(url.username),
      password: decodeURIComponent(url.password),
      database: url.pathname.replace(/^\//, ''),
      ssl: ssl,
      waitForConnections: true,
      connectionLimit: 10,
      queueLimit: 0,
    };
  } catch (err: any) {
    console.error('Failed to parse database configuration:', err.message);
    return null;
  }
}

export function createSessionStore(sessionInstance: any) {
  const config = getDatabaseConfig();
  if (!config) return undefined;

  try {
    const MySQLStore = (MySQLStoreFactory as any)(sessionInstance);
    const store = new MySQLStore({
      host: config.host,
      port: config.port,
      user: config.user,
      password: config.password,
      database: config.database,
      ssl: config.ssl,
      createDatabaseTable: true,
      schema: {
        tableName: 'express_sessions',
      },
    });

    console.log('MySQL session storage configured successfully via express_sessions.');
    return store;
  } catch (err: any) {
    console.error('Failed to initialize MySQL session store:', err.message);
    return undefined;
  }
}

function mapDbZone(row: any): ParkingZone {
  return {
    id: String(row.id),
    name: row.name,
    khmer_name: row.khmer_name || row.name,
    slug: row.slug,
    num_of_slots: Number(row.num_of_slots) || 0,
    occupied_slots: Number(row.occupied_slots) || 0,
    vacant_slots: Number(row.vacant_slots) || 0,
    address: row.address || '',
    district: row.district || '',
    price: Number(row.price) || 3000,
    operating_hours: row.operating_hours || '24/7',
    description: row.description || '',
  };
}

function mapDbReservation(row: any): Reservation {
  return {
    id: String(row.id),
    ticket_code: row.ticket_code,
    customer: row.customer || '',
    start_date: row.start_date || '',
    finish_date: row.finish_date || '',
    parking_zone: row.parking_zone || '',
    parking_zone_slug: row.parking_zone_slug || '',
    plate_number: row.plate_number || '',
    phone_number: row.phone_number || '',
    checked_out: Boolean(row.checked_out),
    created_on: row.created_on || '',
  };
}

export class DatabaseStore {
  private pool: Pool | null = null;
  private memoryUsers: Map<string, User> = new Map();
  private memoryZones: Map<string, ParkingZone> = new Map();
  private memoryReservations: Reservation[] = [];
  public isUsingMySql: boolean = false;

  constructor() {
    this.seedFallbackData();
    this.initPool();
  }

  private initPool() {
    const config = getDatabaseConfig();
    if (!config) {
      console.log('No DATABASE_URL configured. Running with in-memory database store.');
      return;
    }

    try {
      this.pool = mysql.createPool(config);
      this.isUsingMySql = true;
      console.log(`Connected to MySQL database at ${config.host}:${config.port}/${config.database}`);
    } catch (err: any) {
      console.error('Failed to initialize MySQL connection pool:', err.message);
      this.pool = null;
      this.isUsingMySql = false;
    }
  }

  private seedFallbackData() {
    const initialZones: ParkingZone[] = [
      {
        id: '1',
        name: 'BKK1 Commercial Plaza',
        khmer_name: 'ចំណតពាណិជ្ជកម្ម បឹងកេងកង១',
        slug: 'bkk1-commercial-plaza',
        num_of_slots: 50,
        occupied_slots: 38,
        vacant_slots: 12,
        address: 'Street 282 (Corner St 51), Sangkat BKK1, Khan Boeung Keng Kang',
        district: 'BKK1',
        price: 4000,
        operating_hours: '24/7 Covered Access',
        description:
          'Central multi-level covered parking in the vibrant BKK1 business, cafe, and dining district.',
      },
      {
        id: '2',
        name: 'City Center Vattanac & Canadia',
        khmer_name: 'ចំណតមជ្ឈមណ្ឌល វឌ្ឍនៈ-កាណាឌីយ៉ា',
        slug: 'city-center-vattanac',
        num_of_slots: 70,
        occupied_slots: 52,
        vacant_slots: 18,
        address: 'Preah Monivong Blvd, Sangkat Srah Chak, Khan Daun Penh',
        district: 'Phnom Penh City Center',
        price: 5000,
        operating_hours: '24/7 Security Patrol',
        description:
          'Premium financial district parking featuring automated boom gates and 24-hour security.',
      },
      {
        id: '3',
        name: 'Olympic Stadium Complex',
        khmer_name: 'ចំណតពហុកីឡដ្ឋានជាតិអូឡាំពិក',
        slug: 'olympic-stadium-complex',
        num_of_slots: 80,
        occupied_slots: 72,
        vacant_slots: 8,
        address: 'Preah Sihanouk Blvd, Sangkat Olympic, Khan Boeng Keng Kang',
        district: 'Olympic',
        price: 2000,
        operating_hours: '05:30 - 22:00',
        description:
          'Convenient parking for sports events, fitness activities, and nearby Olympic Market shoppers.',
      },
      {
        id: '4',
        name: 'Riverside Promenade Parking',
        khmer_name: 'ចំណតមាត់ទន្លេ ស៊ីសុវត្ថិ',
        slug: 'riverside-promenade',
        num_of_slots: 45,
        occupied_slots: 14,
        vacant_slots: 31,
        address: 'Preah Sisowath Quay, Sangkat Chey Chumneah, Khan Daun Penh',
        district: 'Riverside',
        price: 3000,
        operating_hours: '06:00 - 23:30',
        description:
          'Scenic parking along Phnom Penh riverside, convenient for restaurants, river cruises, and Royal Palace visitors.',
      },
      {
        id: '5',
        name: 'Toul Kork Plaza Hub',
        khmer_name: 'ចំណតផ្សារទួលគោក ផ្លូវ៣១៥',
        slug: 'toul-kork-plaza',
        num_of_slots: 60,
        occupied_slots: 22,
        vacant_slots: 38,
        address: 'Street 315, Sangkat Boeung Kak 1, Khan Toul Kork',
        district: 'Toul Kork',
        price: 2500,
        operating_hours: '06:00 - 22:00',
        description:
          'Spacious parking lot with direct access to TK Avenue and commercial shopping in Toul Kork.',
      },
      {
        id: '6',
        name: 'Sen Sok Central Lot',
        khmer_name: 'ចំណតសែនសុខ កណ្តាលក្រុង',
        slug: 'sen-sok-central',
        num_of_slots: 90,
        occupied_slots: 40,
        vacant_slots: 50,
        address: 'Street 1003, Sangkat Phnom Penh Thmey, Khan Sen Sok',
        district: 'Sen Sok',
        price: 3000,
        operating_hours: '08:00 - 22:30',
        description:
          'High-capacity parking facility serving the growing Sen Sok retail and entertainment area.',
      },
    ];

    for (const zone of initialZones) {
      this.memoryZones.set(zone.slug, zone);
    }
  }

  // Users
  async getUserByUsername(username: string): Promise<User | undefined> {
    if (this.pool) {
      try {
        const [rows]: any = await this.pool.query(
          'SELECT id, username, password FROM auth_user WHERE LOWER(username) = LOWER(?) LIMIT 1',
          [username.trim()]
        );
        if (rows && rows.length > 0) {
          return {
            id: String(rows[0].id),
            username: rows[0].username,
            passwordHash: rows[0].password,
          };
        }
        return undefined;
      } catch (err: any) {
        console.error('Error fetching user from MySQL auth_user:', err.message);
      }
    }
    return this.memoryUsers.get(username.toLowerCase());
  }

  async verifyUser(username: string, plainPassword: string): Promise<User | null> {
    const user = await this.getUserByUsername(username);
    if (!user) return null;
    if (verifyPassword(plainPassword, user.passwordHash)) {
      return user;
    }
    return null;
  }

  async createUser(username: string, plainPassword: string): Promise<User> {
    const passwordHash = hashPassword(plainPassword);
    if (this.pool) {
      try {
        const [result]: any = await this.pool.query(
          `INSERT INTO auth_user (username, password, is_superuser, is_staff, is_active, date_joined, first_name, last_name, email)
           VALUES (?, ?, 0, 0, 1, NOW(6), '', '', '')`,
          [username.trim(), passwordHash]
        );
        return {
          id: String(result.insertId),
          username: username.trim(),
          passwordHash,
        };
      } catch (err: any) {
        console.error('Error creating user in MySQL auth_user:', err.message);
      }
    }

    const user: User = {
      id: String(this.memoryUsers.size + 1),
      username: username.trim(),
      passwordHash,
    };
    this.memoryUsers.set(username.toLowerCase(), user);
    return user;
  }

  // Parking Zones
  async getAllParkingZones(): Promise<ParkingZoneView[]> {
    if (this.pool) {
      try {
        const [rows]: any = await this.pool.query(
          `SELECT id, name, khmer_name, slug, num_of_slots, occupied_slots, vacant_slots,
                  address, district, price, operating_hours, description
           FROM parking_zones_parkingzone
           ORDER BY id ASC`
        );
        if (rows && rows.length > 0) {
          return rows.map((r: any) => toZoneView(mapDbZone(r)));
        }
      } catch (err: any) {
        console.error('Error fetching parking zones from MySQL:', err.message);
      }
    }
    return Array.from(this.memoryZones.values()).map(toZoneView);
  }

  async getFilteredParkingZones(query?: string, district?: string): Promise<ParkingZoneView[]> {
    const zones = await this.getAllParkingZones();
    let filtered = zones;

    if (district && district.trim()) {
      const d = district.trim().toLowerCase();
      filtered = filtered.filter((z) => z.district.toLowerCase() === d);
    }

    if (query && query.trim()) {
      const q = query.trim().toLowerCase();
      filtered = filtered.filter(
        (z) =>
          z.name.toLowerCase().includes(q) ||
          z.khmer_name.toLowerCase().includes(q) ||
          z.address.toLowerCase().includes(q) ||
          z.district.toLowerCase().includes(q)
      );
    }

    return filtered;
  }

  async getDistricts(): Promise<string[]> {
    const zones = await this.getAllParkingZones();
    const set = new Set<string>();
    for (const z of zones) {
      if (z.district) set.add(z.district);
    }
    return Array.from(set);
  }

  async getAggregates(): Promise<{ total_slots: number; total_occupied: number; total_vacant: number }> {
    const zones = await this.getAllParkingZones();
    let total_slots = 0;
    let total_occupied = 0;
    let total_vacant = 0;

    for (const zone of zones) {
      total_slots += zone.num_of_slots;
      total_occupied += zone.occupied_slots;
      total_vacant += zone.vacant_slots;
    }

    return { total_slots, total_occupied, total_vacant };
  }

  async getParkingZoneBySlug(slug: string): Promise<ParkingZoneView | undefined> {
    if (this.pool) {
      try {
        const [rows]: any = await this.pool.query(
          `SELECT id, name, khmer_name, slug, num_of_slots, occupied_slots, vacant_slots,
                  address, district, price, operating_hours, description
           FROM parking_zones_parkingzone
           WHERE slug = ? LIMIT 1`,
          [slug]
        );
        if (rows && rows.length > 0) {
          return toZoneView(mapDbZone(rows[0]));
        }
      } catch (err: any) {
        console.error('Error fetching parking zone by slug from MySQL:', err.message);
      }
    }
    const zone = this.memoryZones.get(slug);
    return zone ? toZoneView(zone) : undefined;
  }

  async getParkingZoneByName(name: string): Promise<ParkingZone | undefined> {
    if (this.pool) {
      try {
        const [rows]: any = await this.pool.query(
          `SELECT id, name, khmer_name, slug, num_of_slots, occupied_slots, vacant_slots,
                  address, district, price, operating_hours, description
           FROM parking_zones_parkingzone
           WHERE LOWER(name) = LOWER(?) LIMIT 1`,
          [name]
        );
        if (rows && rows.length > 0) {
          return mapDbZone(rows[0]);
        }
      } catch (err: any) {
        console.error('Error fetching parking zone by name from MySQL:', err.message);
      }
    }
    for (const zone of this.memoryZones.values()) {
      if (zone.name.toLowerCase() === name.toLowerCase()) {
        return zone;
      }
    }
    return undefined;
  }

  // Reservations
  async getActiveReservation(username: string): Promise<Reservation | undefined> {
    if (this.pool) {
      try {
        const [rows]: any = await this.pool.query(
          `SELECT r.id, r.ticket_code, u.username as customer,
                  DATE_FORMAT(r.start_date, '%Y-%m-%d') as start_date,
                  DATE_FORMAT(r.finish_date, '%Y-%m-%d') as finish_date,
                  z.name as parking_zone, z.slug as parking_zone_slug,
                  r.plate_number, r.phone_number, r.checked_out,
                  DATE_FORMAT(r.created_on, '%d %b %Y') as created_on
           FROM parking_zones_reservation r
           JOIN auth_user u ON r.customer_id = u.id
           JOIN parking_zones_parkingzone z ON r.parking_zone_id = z.id
           WHERE LOWER(u.username) = LOWER(?) AND r.checked_out = 0
           ORDER BY r.id DESC LIMIT 1`,
          [username.trim()]
        );
        if (rows && rows.length > 0) {
          return mapDbReservation(rows[0]);
        }
        return undefined;
      } catch (err: any) {
        console.error('Error fetching active reservation from MySQL:', err.message);
      }
    }

    return this.memoryReservations.find(
      (r) => r.customer.toLowerCase() === username.toLowerCase() && !r.checked_out
    );
  }

  async getUserReservations(username: string): Promise<Reservation[]> {
    if (this.pool) {
      try {
        const [rows]: any = await this.pool.query(
          `SELECT r.id, r.ticket_code, u.username as customer,
                  DATE_FORMAT(r.start_date, '%Y-%m-%d') as start_date,
                  DATE_FORMAT(r.finish_date, '%Y-%m-%d') as finish_date,
                  z.name as parking_zone, z.slug as parking_zone_slug,
                  r.plate_number, r.phone_number, r.checked_out,
                  DATE_FORMAT(r.created_on, '%d %b %Y') as created_on
           FROM parking_zones_reservation r
           JOIN auth_user u ON r.customer_id = u.id
           JOIN parking_zones_parkingzone z ON r.parking_zone_id = z.id
           WHERE LOWER(u.username) = LOWER(?)
           ORDER BY r.id DESC`,
          [username.trim()]
        );
        return rows.map(mapDbReservation);
      } catch (err: any) {
        console.error('Error fetching user reservations from MySQL:', err.message);
      }
    }

    return this.memoryReservations.filter(
      (r) => r.customer.toLowerCase() === username.toLowerCase()
    );
  }

  async getReservationByTicketCode(ticketCode: string): Promise<Reservation | undefined> {
    if (this.pool) {
      try {
        const [rows]: any = await this.pool.query(
          `SELECT r.id, r.ticket_code, u.username as customer,
                  DATE_FORMAT(r.start_date, '%Y-%m-%d') as start_date,
                  DATE_FORMAT(r.finish_date, '%Y-%m-%d') as finish_date,
                  z.name as parking_zone, z.slug as parking_zone_slug,
                  r.plate_number, r.phone_number, r.checked_out,
                  DATE_FORMAT(r.created_on, '%d %b %Y') as created_on
           FROM parking_zones_reservation r
           LEFT JOIN auth_user u ON r.customer_id = u.id
           JOIN parking_zones_parkingzone z ON r.parking_zone_id = z.id
           WHERE UPPER(r.ticket_code) = UPPER(?) LIMIT 1`,
          [ticketCode.trim()]
        );
        if (rows && rows.length > 0) {
          return mapDbReservation(rows[0]);
        }
        return undefined;
      } catch (err: any) {
        console.error('Error fetching reservation by ticket code from MySQL:', err.message);
      }
    }

    return this.memoryReservations.find(
      (r) => r.ticket_code.toUpperCase() === ticketCode.toUpperCase()
    );
  }

  async createReservation(
    username: string,
    zoneIdentifier: string,
    startDate: string,
    finishDate: string,
    plateNumber: string,
    phoneNumber: string
  ): Promise<{ success: boolean; message: string; reservation?: Reservation }> {
    let zone: ParkingZone | undefined = await this.getParkingZoneBySlug(zoneIdentifier);
    if (!zone) {
      zone = await this.getParkingZoneByName(zoneIdentifier);
    }

    if (!zone) {
      return { success: false, message: 'Parking Zone not found!' };
    }

    if (zone.vacant_slots <= 0) {
      return { success: false, message: 'Sorry, this parking zone is full (ពេញ)!' };
    }

    const existing = await this.getActiveReservation(username);
    if (existing) {
      return {
        success: false,
        message: `You already have an active reservation at ${existing.parking_zone} (Ticket: ${existing.ticket_code}). Please check out first.`,
      };
    }

    const ticketCode = generateTicketCode();
    const accessToken = crypto.randomBytes(32).toString('hex');

    if (this.pool) {
      try {
        const [userRows]: any = await this.pool.query(
          'SELECT id FROM auth_user WHERE LOWER(username) = LOWER(?) LIMIT 1',
          [username.trim()]
        );
        const customerId = userRows && userRows.length > 0 ? userRows[0].id : null;

        const [resResult]: any = await this.pool.query(
          `INSERT INTO parking_zones_reservation (
            ticket_code, start_date, finish_date, plate_number, phone_number,
            checked_out, created_on, customer_id, parking_zone_id,
            access_token, balance_paid, daily_rate, deposit_amount,
            is_legacy, overstay_multiplier, payment_method, payment_status,
            status, total_amount, reserved_days, deposit_forfeited, is_walk_in, plate_lookup_hmac
          ) VALUES (
            ?, ?, ?, ?, ?,
            0, NOW(6), ?, ?,
            ?, 0, ?, 0,
            0, 1.0, 'PAY_AT_EXIT', 'PENDING',
            'CONFIRMED', ?, 1, 0, 0, ''
          )`,
          [
            ticketCode,
            startDate,
            finishDate,
            plateNumber.trim().toUpperCase(),
            phoneNumber.trim(),
            customerId,
            zone.id,
            accessToken,
            zone.price,
            zone.price,
          ]
        );

        // Update zone capacity
        await this.pool.query(
          `UPDATE parking_zones_parkingzone
           SET occupied_slots = LEAST(num_of_slots, occupied_slots + 1),
               vacant_slots = GREATEST(0, num_of_slots - (occupied_slots + 1))
           WHERE id = ?`,
          [zone.id]
        );

        const reservation: Reservation = {
          id: String(resResult.insertId),
          ticket_code: ticketCode,
          customer: username,
          start_date: startDate,
          finish_date: finishDate,
          parking_zone: zone.name,
          parking_zone_slug: zone.slug,
          plate_number: plateNumber.trim().toUpperCase(),
          phone_number: phoneNumber.trim(),
          checked_out: false,
          created_on: new Date().toLocaleDateString('en-GB', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
          }),
        };

        return { success: true, message: 'Successfully Booked', reservation };
      } catch (err: any) {
        console.error('Error creating reservation in MySQL:', err.message);
      }
    }

    // In-memory fallback
    const reservation: Reservation = {
      id: String(this.memoryReservations.length + 1),
      ticket_code: ticketCode,
      customer: username,
      start_date: startDate,
      finish_date: finishDate,
      parking_zone: zone.name,
      parking_zone_slug: zone.slug,
      plate_number: plateNumber.trim().toUpperCase(),
      phone_number: phoneNumber.trim(),
      checked_out: false,
      created_on: new Date().toLocaleDateString('en-GB', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      }),
    };

    this.memoryReservations.unshift(reservation);
    zone.occupied_slots = Math.min(zone.num_of_slots, zone.occupied_slots + 1);
    zone.vacant_slots = Math.max(0, zone.num_of_slots - zone.occupied_slots);

    return { success: true, message: 'Successfully Booked', reservation };
  }

  async checkOutReservation(
    username: string,
    ticketCode?: string
  ): Promise<{ success: boolean; message: string }> {
    if (this.pool) {
      try {
        let query = `
          SELECT r.id, r.ticket_code, r.parking_zone_id, r.checked_out, z.name as parking_zone, u.username as customer
          FROM parking_zones_reservation r
          JOIN parking_zones_parkingzone z ON r.parking_zone_id = z.id
          LEFT JOIN auth_user u ON r.customer_id = u.id
        `;
        const params: any[] = [];

        if (ticketCode) {
          query += ` WHERE UPPER(r.ticket_code) = UPPER(?) LIMIT 1`;
          params.push(ticketCode.trim());
        } else {
          query += ` WHERE LOWER(u.username) = LOWER(?) AND r.checked_out = 0 ORDER BY r.id DESC LIMIT 1`;
          params.push(username.trim());
        }

        const [rows]: any = await this.pool.query(query, params);
        if (!rows || rows.length === 0) {
          return { success: false, message: 'No active parking reservation exists' };
        }

        const resRow = rows[0];
        if (resRow.customer && resRow.customer.toLowerCase() !== username.toLowerCase()) {
          return { success: false, message: 'Unauthorized ticket access' };
        }

        if (resRow.checked_out) {
          return {
            success: false,
            message: `Ticket ${resRow.ticket_code} has already been checked out.`,
          };
        }

        // Mark checked out
        await this.pool.query(
          `UPDATE parking_zones_reservation
           SET checked_out = 1, status = 'CHECKED_OUT', checked_out_at = NOW(6), payment_status = 'PAID'
           WHERE id = ?`,
          [resRow.id]
        );

        // Update zone capacity
        await this.pool.query(
          `UPDATE parking_zones_parkingzone
           SET occupied_slots = GREATEST(0, occupied_slots - 1),
               vacant_slots = LEAST(num_of_slots, num_of_slots - (occupied_slots - 1))
           WHERE id = ?`,
          [resRow.parking_zone_id]
        );

        return { success: true, message: `Successfully checked out of ${resRow.parking_zone}` };
      } catch (err: any) {
        console.error('Error checking out reservation in MySQL:', err.message);
      }
    }

    // In-memory fallback
    let reservation: Reservation | undefined;
    if (ticketCode) {
      reservation = await this.getReservationByTicketCode(ticketCode);
      if (reservation && reservation.customer.toLowerCase() !== username.toLowerCase()) {
        return { success: false, message: 'Unauthorized ticket access' };
      }
    } else {
      reservation = await this.getActiveReservation(username);
    }

    if (!reservation) {
      return { success: false, message: 'No active parking reservation exists' };
    }

    if (reservation.checked_out) {
      return {
        success: false,
        message: `Ticket ${reservation.ticket_code} has already been checked out.`,
      };
    }

    reservation.checked_out = true;
    const zone = await this.getParkingZoneByName(reservation.parking_zone);
    if (zone) {
      zone.occupied_slots = Math.max(0, zone.occupied_slots - 1);
      zone.vacant_slots = Math.min(zone.num_of_slots, zone.num_of_slots - zone.occupied_slots);
    }

    return { success: true, message: `Successfully checked out of ${reservation.parking_zone}` };
  }
}

export const dbStore = new DatabaseStore();
