import express from 'express';
import session from 'express-session';
import cookieParser from 'cookie-parser';
import path from 'path';
import { fileURLToPath } from 'url';
import { existsSync } from 'node:fs';
import { loadEnvFile } from 'node:process';
import bcrypt from 'bcryptjs';
import { dbStore } from './src/store.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Node 20.12+ loads local secrets while preserving deployment environment values.
const envPath = path.join(__dirname, '.env');
if (existsSync(envPath)) loadEnvFile(envPath);
const sessionSecret = process.env.SESSION_SECRET?.trim();
if (!sessionSecret) {
  throw new Error('Set SESSION_SECRET in .env or the deployment environment before starting Express.');
}

const app = express();
const PORT = 3000;
const HOST = '0.0.0.0';

// Template engine
app.set('view engine', 'ejs');
app.set('views', path.join(process.cwd(), 'views'));

// Middlewares
app.use(express.urlencoded({ extended: true }));
app.use(express.json());
app.use(cookieParser() as any);
app.use(
  session({
    secret: sessionSecret,
    resave: false,
    saveUninitialized: false,
    cookie: { maxAge: 24 * 60 * 60 * 1000 },
  }) as any
);

// Static assets: serve /static from ./static AND ./public
app.use('/static', express.static(path.join(process.cwd(), 'static')));
app.use(express.static(path.join(process.cwd(), 'public')));
app.use('/static/source', express.static(path.join(process.cwd(), 'public')));

// Extend session type
declare module 'express-session' {
  interface SessionData {
    user?: {
      id: string;
      username: string;
    };
    messages?: Array<{ type: string; text: string }>;
  }
}

// Flash messages & user context middleware
app.use((req, res, next) => {
  res.locals.user = req.session.user || null;
  res.locals.messages = req.session.messages || [];
  req.session.messages = [];

  // Provide active reservation to all views if user is logged in
  if (req.session.user) {
    res.locals.active_reservation = dbStore.getActiveReservation(req.session.user.username) || null;
  } else {
    res.locals.active_reservation = null;
  }

  next();
});

function flash(req: express.Request, type: string, text: string) {
  if (!req.session.messages) {
    req.session.messages = [];
  }
  req.session.messages.push({ type, text });
}

function requireAuth(req: express.Request, res: express.Response, next: express.NextFunction) {
  if (!req.session || !req.session.user) {
    flash(req, 'warning', 'Please sign in to access your reservations');
    return res.redirect('/user/login');
  }
  next();
}

// Health check endpoint
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', service: 'SomPark Phnom Penh' });
});

// Home page with search, district filtering, and stats
app.get('/', (req, res) => {
  const q = typeof req.query.q === 'string' ? req.query.q.trim() : '';
  const district = typeof req.query.district === 'string' ? req.query.district.trim() : '';

  const all_parking_zones = dbStore.getFilteredParkingZones(q, district);
  const aggregates = dbStore.getAggregates();
  const districts = dbStore.getDistricts();

  res.render('index', {
    all_parking_zones,
    aggregates,
    districts,
    search_query: q,
    selected_district: district,
    title: 'SomPark - Phnom Penh Smart Parking',
  });
});

// Zone details
app.get('/zone/:slug/', (req, res) => {
  const parking_zone = dbStore.getParkingZoneBySlug(req.params.slug);
  if (!parking_zone) {
    flash(req, 'warning', 'Parking Zone not found');
    return res.redirect('/#parking-zones');
  }
  res.render('status', {
    parking_zone,
    title: `${parking_zone.name} Details | SomPark`,
  });
});

// User signup
app.get('/user/signup/', (req, res) => {
  if (req.session.user) {
    return res.redirect('/');
  }
  res.render('signup', { title: 'Create Account | SomPark' });
});

app.post('/user/signup/', (req, res) => {
  const { username, password, password_confirm } = req.body;

  if (!username || !password) {
    flash(req, 'warning', 'Please fill in all required fields');
    return res.render('signup', { title: 'Create Account | SomPark', error: 'Please fill in all fields' });
  }

  if (password.length < 6) {
    flash(req, 'warning', 'Password must be at least 6 characters long');
    return res.render('signup', { title: 'Create Account | SomPark', error: 'Password must be at least 6 characters' });
  }

  if (password !== password_confirm) {
    flash(req, 'warning', 'Passwords do not match');
    return res.render('signup', { title: 'Create Account | SomPark', error: 'Passwords do not match' });
  }

  if (dbStore.getUserByUsername(username)) {
    flash(req, 'warning', 'Username already taken');
    return res.render('signup', { title: 'Create Account | SomPark', error: 'Username already taken' });
  }

  dbStore.createUser(username.trim(), password);
  flash(req, 'success', `Successfully created user ${username}. You can now sign in.`);
  res.redirect('/user/login');
});

// User login
app.get('/user/login', (req, res) => {
  if (req.session.user) {
    return res.redirect('/');
  }
  res.render('login', { title: 'Sign In | SomPark' });
});

app.post('/user/login', (req, res) => {
  const { username, password } = req.body;
  const user = dbStore.getUserByUsername(username || '');

  if (!user || !bcrypt.compareSync(password || '', user.passwordHash)) {
    flash(req, 'warning', 'Invalid username or password');
    return res.render('login', { title: 'Sign In | SomPark', error: 'Invalid credentials. Try demo / password123' });
  }

  req.session.user = {
    id: user.id,
    username: user.username,
  };

  flash(req, 'success', `Welcome back, ${user.username}!`);
  res.redirect('/');
});

// User logout
app.get('/user/logout/', (req, res) => {
  req.session.destroy(() => {
    res.redirect('/user/login');
  });
});

// Reservation form
app.get('/book/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const activeReservation = dbStore.getActiveReservation(username);

  const today = new Date().toISOString().split('T')[0];
  const parking_zones = dbStore.getAllParkingZones();
  const selected_zone = typeof req.query.zone === 'string' ? req.query.zone : '';

  res.render('booking', {
    parking_zones,
    selected_zone,
    active_reservation: activeReservation,
    minDate: today,
    title: 'Reserve Parking Spot | SomPark',
  });
});

app.post('/book/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const activeReservation = dbStore.getActiveReservation(username);

  if (activeReservation) {
    flash(req, 'warning', `You already have an active spot at ${activeReservation.parking_zone}. Please check out first.`);
    return res.redirect(`/ticket/${activeReservation.ticket_code}`);
  }

  const { start_date, finish_date, parking_zone, plate_number, phone_number } = req.body;
  const today = new Date().toISOString().split('T')[0];

  if (!start_date || !finish_date || !parking_zone || !plate_number || !phone_number) {
    flash(req, 'warning', 'All fields are required');
    return res.redirect('/book/');
  }

  if (start_date > finish_date) {
    flash(req, 'warning', 'Finish date cannot be before start date.');
    return res.redirect('/book/');
  }

  if (start_date < today) {
    flash(req, 'warning', 'Start date cannot be in the past.');
    return res.redirect('/book/');
  }

  const result = dbStore.createReservation(
    username,
    parking_zone,
    start_date,
    finish_date,
    plate_number,
    phone_number
  );

  if (!result.success || !result.reservation) {
    flash(req, 'warning', result.message);
    return res.redirect('/book/');
  }

  flash(req, 'success', `Parking spot booked successfully! Reference code: ${result.reservation.ticket_code}`);
  res.redirect(`/ticket/${result.reservation.ticket_code}`);
});

// Ticket View by code or latest
app.get('/ticket/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const reservations = dbStore.getUserReservations(username);

  if (!reservations || reservations.length === 0) {
    flash(req, 'warning', `No parking reservations found for ${username}`);
    return res.redirect('/#parking-zones');
  }

  res.redirect(`/ticket/${reservations[0].ticket_code}`);
});

app.get('/ticket/:code', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const ticketCode = req.params.code;
  const reservation = dbStore.getReservationByTicketCode(ticketCode);

  if (!reservation || reservation.customer.toLowerCase() !== username.toLowerCase()) {
    flash(req, 'warning', 'Ticket not found or unauthorized');
    return res.redirect('/all_tickets/');
  }

  const today = new Date().toLocaleDateString('en-GB', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

  res.render('ticket', {
    reservation,
    today,
    title: `Ticket #${reservation.ticket_code} | SomPark`,
  });
});

// All Tickets History
app.get('/all_tickets/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const reservations = dbStore.getUserReservations(username);

  const today = new Date().toLocaleDateString('en-GB', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

  res.render('all_tickets', {
    reservations,
    today,
    title: 'All Tickets | SomPark',
  });
});

// Checkout (support both GET and POST)
const handleCheckout = (req: express.Request, res: express.Response) => {
  const username = req.session.user!.username;
  const ticketCode = (req.body?.ticket_code || req.query?.ticket_code || '') as string;

  const result = dbStore.checkOutReservation(username, ticketCode || undefined);

  if (result.success) {
    flash(req, 'success', result.message);
  } else {
    flash(req, 'warning', result.message);
  }

  res.redirect('/all_tickets/');
};

app.post('/checkout/', requireAuth, handleCheckout);
app.get('/checkout/', requireAuth, handleCheckout);

// Fallback route
app.use((req, res) => {
  res.redirect('/');
});

// Start server
app.listen(PORT, HOST, () => {
  console.log(`SomPark server running on http://${HOST}:${PORT}`);
});
