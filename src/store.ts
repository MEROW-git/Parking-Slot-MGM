import bcrypt from 'bcryptjs';

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

// In-Memory Database Store
class DatabaseStore {
  users: Map<string, User> = new Map();
  parkingZones: Map<string, ParkingZone> = new Map();
  reservations: Reservation[] = [];

  constructor() {
    this.seedInitialData();
  }

  private seedInitialData() {
    // Seed default demo user (demo / password123)
    const demoPasswordHash = bcrypt.hashSync('password123', 10);
    this.users.set('demo', {
      id: '1',
      username: 'demo',
      passwordHash: demoPasswordHash,
    });

    // Seed Phnom Penh Parking Zones matching SomPark database
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
      this.parkingZones.set(zone.slug, zone);
    }
  }

  // Users
  getUserByUsername(username: string): User | undefined {
    return this.users.get(username.toLowerCase());
  }

  createUser(username: string, plainPassword: string): User {
    const passwordHash = bcrypt.hashSync(plainPassword, 10);
    const user: User = {
      id: String(this.users.size + 1),
      username: username,
      passwordHash,
    };
    this.users.set(username.toLowerCase(), user);
    return user;
  }

  // Parking Zones
  getAllParkingZones(): ParkingZoneView[] {
    return Array.from(this.parkingZones.values()).map(toZoneView);
  }

  getFilteredParkingZones(query?: string, district?: string): ParkingZoneView[] {
    let zones = Array.from(this.parkingZones.values());

    if (district && district.trim()) {
      const d = district.trim().toLowerCase();
      zones = zones.filter((z) => z.district.toLowerCase() === d);
    }

    if (query && query.trim()) {
      const q = query.trim().toLowerCase();
      zones = zones.filter(
        (z) =>
          z.name.toLowerCase().includes(q) ||
          z.khmer_name.toLowerCase().includes(q) ||
          z.address.toLowerCase().includes(q) ||
          z.district.toLowerCase().includes(q)
      );
    }

    return zones.map(toZoneView);
  }

  getDistricts(): string[] {
    const set = new Set<string>();
    for (const zone of this.parkingZones.values()) {
      set.add(zone.district);
    }
    return Array.from(set);
  }

  getAggregates() {
    let total_slots = 0;
    let total_occupied = 0;
    let total_vacant = 0;

    for (const zone of this.parkingZones.values()) {
      total_slots += zone.num_of_slots;
      total_occupied += zone.occupied_slots;
      total_vacant += zone.vacant_slots;
    }

    return { total_slots, total_occupied, total_vacant };
  }

  getParkingZoneBySlug(slug: string): ParkingZoneView | undefined {
    const zone = this.parkingZones.get(slug);
    return zone ? toZoneView(zone) : undefined;
  }

  getParkingZoneByName(name: string): ParkingZone | undefined {
    for (const zone of this.parkingZones.values()) {
      if (zone.name.toLowerCase() === name.toLowerCase()) {
        return zone;
      }
    }
    return undefined;
  }

  // Reservations
  getActiveReservation(username: string): Reservation | undefined {
    return this.reservations.find(
      (r) => r.customer.toLowerCase() === username.toLowerCase() && !r.checked_out
    );
  }

  getUserReservations(username: string): Reservation[] {
    return this.reservations.filter(
      (r) => r.customer.toLowerCase() === username.toLowerCase()
    );
  }

  getReservationByTicketCode(ticketCode: string): Reservation | undefined {
    return this.reservations.find(
      (r) => r.ticket_code.toUpperCase() === ticketCode.toUpperCase()
    );
  }

  createReservation(
    username: string,
    zoneIdentifier: string, // name or slug
    startDate: string,
    finishDate: string,
    plateNumber: string,
    phoneNumber: string
  ): { success: boolean; message: string; reservation?: Reservation } {
    let zone = this.parkingZones.get(zoneIdentifier);
    if (!zone) {
      zone = this.getParkingZoneByName(zoneIdentifier);
    }

    if (!zone) {
      return { success: false, message: 'Parking Zone not found!' };
    }

    if (zone.vacant_slots <= 0) {
      return { success: false, message: 'Sorry, this parking zone is full (ពេញ)!' };
    }

    const existing = this.getActiveReservation(username);
    if (existing) {
      return {
        success: false,
        message: `You already have an active reservation at ${existing.parking_zone} (Ticket: ${existing.ticket_code}). Please check out first.`,
      };
    }

    const reservation: Reservation = {
      id: String(this.reservations.length + 1),
      ticket_code: generateTicketCode(),
      customer: username,
      start_date: startDate,
      finish_date: finishDate,
      parking_zone: zone.name,
      parking_zone_slug: zone.slug,
      plate_number: plateNumber.toUpperCase(),
      phone_number: phoneNumber,
      checked_out: false,
      created_on: new Date().toLocaleDateString('en-GB', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      }),
    };

    this.reservations.unshift(reservation);

    // Update parking zone counts
    zone.occupied_slots = Math.min(zone.num_of_slots, zone.occupied_slots + 1);
    zone.vacant_slots = Math.max(0, zone.num_of_slots - zone.occupied_slots);

    return { success: true, message: 'Successfully Booked', reservation };
  }

  checkOutReservation(username: string, ticketCode?: string): { success: boolean; message: string } {
    let reservation: Reservation | undefined;

    if (ticketCode) {
      reservation = this.getReservationByTicketCode(ticketCode);
      if (reservation && reservation.customer.toLowerCase() !== username.toLowerCase()) {
        return { success: false, message: 'Unauthorized ticket access' };
      }
    } else {
      reservation = this.getActiveReservation(username);
    }

    if (!reservation) {
      return {
        success: false,
        message: `No active parking reservation exists`,
      };
    }

    if (reservation.checked_out) {
      return {
        success: false,
        message: `Ticket ${reservation.ticket_code} has already been checked out.`,
      };
    }

    reservation.checked_out = true;

    const zone = this.getParkingZoneByName(reservation.parking_zone);
    if (zone) {
      zone.occupied_slots = Math.max(0, zone.occupied_slots - 1);
      zone.vacant_slots = Math.min(zone.num_of_slots, zone.num_of_slots - zone.occupied_slots);
    }

    return { success: true, message: `Successfully checked out of ${reservation.parking_zone}` };
  }
}

export const dbStore = new DatabaseStore();

