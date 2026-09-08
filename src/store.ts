import bcrypt from 'bcryptjs';

export interface User {
  id: string;
  username: string;
  passwordHash: string;
}

export interface ParkingZone {
  id: string;
  name: string;
  slug: string;
  num_of_slots: number;
  occupied_slots: number;
  vacant_slots: number;
  address: string;
  price: number;
}

export interface Reservation {
  id: string;
  ticket_code: string;
  customer: string; // username
  start_date: string;
  finish_date: string;
  parking_zone: string; // zone name
  plate_number: string;
  phone_number: string;
  checked_out: boolean;
  created_on: string;
}

export function generateTicketCode(): string {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < 6; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
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

    // Seed Parking Zones
    const initialZones: ParkingZone[] = [
      {
        id: '1',
        name: 'Downtown Plaza Parking',
        slug: 'downtown-plaza',
        num_of_slots: 40,
        occupied_slots: 12,
        vacant_slots: 28,
        address: '100 Main Street, Downtown',
        price: 15,
      },
      {
        id: '2',
        name: 'Central Station Garage',
        slug: 'central-station',
        num_of_slots: 60,
        occupied_slots: 45,
        vacant_slots: 15,
        address: '450 5th Avenue, Midtown',
        price: 20,
      },
      {
        id: '3',
        name: 'Harbor View Parking',
        slug: 'harbor-view',
        num_of_slots: 25,
        occupied_slots: 5,
        vacant_slots: 20,
        address: '88 Bay Street, Waterfront',
        price: 10,
      },
      {
        id: '4',
        name: 'Airport Express Lot',
        slug: 'airport-express',
        num_of_slots: 100,
        occupied_slots: 82,
        vacant_slots: 18,
        address: 'Terminal 2 Blvd, Airport',
        price: 25,
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
  getAllParkingZones(): ParkingZone[] {
    return Array.from(this.parkingZones.values());
  }

  getParkingZoneBySlug(slug: string): ParkingZone | undefined {
    return this.parkingZones.get(slug);
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

  createReservation(
    username: string,
    zoneName: string,
    startDate: string,
    finishDate: string,
    plateNumber: string,
    phoneNumber: string
  ): { success: boolean; message: string; reservation?: Reservation } {
    const zone = this.getParkingZoneByName(zoneName);
    if (!zone) {
      return { success: false, message: 'Parking Zone not found!' };
    }

    if (zone.vacant_slots <= 0) {
      return { success: false, message: 'Parking Zone Full!' };
    }

    const existing = this.getActiveReservation(username);
    if (existing) {
      return {
        success: false,
        message: 'Please Check Out Your Previous Reservation',
      };
    }

    const reservation: Reservation = {
      id: String(this.reservations.length + 1),
      ticket_code: generateTicketCode(),
      customer: username,
      start_date: startDate,
      finish_date: finishDate,
      parking_zone: zone.name,
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
    zone.occupied_slots += 1;
    zone.vacant_slots = Math.max(0, zone.num_of_slots - zone.occupied_slots);

    return { success: true, message: 'Successfully Booked', reservation };
  }

  checkOutReservation(username: string): { success: boolean; message: string } {
    const reservation = this.getActiveReservation(username);
    if (!reservation) {
      return {
        success: false,
        message: `No Parking reservation exists for ${username}`,
      };
    }

    reservation.checked_out = true;

    const zone = this.getParkingZoneByName(reservation.parking_zone);
    if (zone) {
      zone.occupied_slots = Math.max(0, zone.occupied_slots - 1);
      zone.vacant_slots = Math.min(zone.num_of_slots, zone.vacant_slots + 1);
    }

    return { success: true, message: 'Successfully Checked Out' };
  }
}

export const dbStore = new DatabaseStore();
