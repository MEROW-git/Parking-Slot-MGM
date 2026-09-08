import express from 'express';
import session from 'express-session';
import cookieParser from 'cookie-parser';
import path from 'path';
import { fileURLToPath } from 'url';
import bcrypt from 'bcryptjs';
import { dbStore } from './src/store.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

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
    secret: process.env.SESSION_SECRET || 'parking-secret-key-avalon-2026',
    resave: false,
    saveUninitialized: false,
    cookie: { maxAge: 24 * 60 * 60 * 1000 },
  }) as any
);

// Static assets (serve from public)
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
    flash(req, 'warning', 'Please login to access this page');
    return res.redirect('/user/login');
  }
  next();
}

// Health check endpoint
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok' });
});

// Home page
app.get('/', (req, res) => {
  const all_parking_zones = dbStore.getAllParkingZones();
  res.render('index', {
    all_parking_zones,
    title: 'Home',
  });
});

// Zone details
app.get('/zone/:slug/', (req, res) => {
  const parking_zone = dbStore.getParkingZoneBySlug(req.params.slug);
  if (!parking_zone) {
    flash(req, 'warning', 'Parking Zone not found');
    return res.redirect('/');
  }
  res.render('status', {
    parking_zone,
    title: `${parking_zone.name} Details`,
  });
});

// User signup
app.get('/user/signup/', (req, res) => {
  if (req.session.user) {
    return res.redirect('/');
  }
  res.render('signup', { title: 'Create Account' });
});

app.post('/user/signup/', (req, res) => {
  const { username, password, password_confirm } = req.body;

  if (!username || !password) {
    flash(req, 'warning', 'Please fill in all required fields');
    return res.render('signup', { title: 'Create Account', error: 'Please fill in all fields' });
  }

  if (password !== password_confirm) {
    flash(req, 'warning', 'Passwords do not match');
    return res.render('signup', { title: 'Create Account', error: 'Passwords do not match' });
  }

  if (dbStore.getUserByUsername(username)) {
    flash(req, 'warning', 'Username already taken');
    return res.render('signup', { title: 'Create Account', error: 'Username already taken' });
  }

  dbStore.createUser(username.trim(), password);
  flash(req, 'success', `Succesfully Created user ${username}. You can now login`);
  res.redirect('/user/login');
});

// User login
app.get('/user/login', (req, res) => {
  if (req.session.user) {
    return res.redirect('/');
  }
  res.render('login', { title: 'Login' });
});

app.post('/user/login', (req, res) => {
  const { username, password } = req.body;
  const user = dbStore.getUserByUsername(username || '');

  if (!user || !bcrypt.compareSync(password || '', user.passwordHash)) {
    flash(req, 'warning', 'invalid Credentials');
    return res.render('login', { title: 'Login', error: 'Invalid credentials' });
  }

  req.session.user = {
    id: user.id,
    username: user.username,
  };

  flash(req, 'success', `User ${user.username} Successfully Logged in`);
  res.redirect('/');
});

// User logout
app.get('/user/logout/', (req, res) => {
  req.session.destroy((err) => {
    res.redirect('/user/login');
  });
});

// Reservation form
app.get('/book/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const activeReservation = dbStore.getActiveReservation(username);

  if (activeReservation) {
    flash(req, 'warning', 'Please Check Out Your Previous Reservation');
    return res.redirect('/');
  }

  const today = new Date().toISOString().split('T')[0];
  const parking_zones = dbStore.getAllParkingZones();

  res.render('booking', {
    parking_zones,
    minDate: today,
    title: 'Book Parking Spot',
  });
});

app.post('/book/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const activeReservation = dbStore.getActiveReservation(username);

  if (activeReservation) {
    flash(req, 'warning', 'Please Check Out Your Previous Reservation');
    return res.redirect('/');
  }

  const { start_date, finish_date, parking_zone, plate_number, phone_number } = req.body;
  const today = new Date().toISOString().split('T')[0];

  if (!start_date || !finish_date || !parking_zone || !plate_number || !phone_number) {
    flash(req, 'warning', 'All fields are required');
    return res.redirect('/book/');
  }

  if (start_date > finish_date) {
    flash(req, 'warning', 'Wrong start and finish dates.');
    return res.redirect('/book/');
  }

  if (start_date < today) {
    flash(req, 'warning', 'Start date in the past.');
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

  if (!result.success) {
    flash(req, 'warning', result.message);
    return res.redirect('/');
  }

  flash(req, 'info', 'Successfully Booked');
  res.redirect('/ticket/');
});

// Ticket View
app.get('/ticket/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const reservations = dbStore.getUserReservations(username);

  if (!reservations || reservations.length === 0) {
    flash(req, 'warning', `No Parking reservation exists for ${username}`);
    return res.redirect('/');
  }

  const latestReservation = reservations[0];
  const today = new Date().toLocaleDateString('en-GB', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

  res.render('ticket', {
    reservation: latestReservation,
    today,
    title: 'Ticket Details',
  });
});

// All Tickets
app.get('/all_tickets/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const reservations = dbStore.getUserReservations(username);

  if (!reservations || reservations.length === 0) {
    flash(req, 'warning', `No Parking reservation exists for ${username}`);
    return res.redirect('/');
  }

  const today = new Date().toLocaleDateString('en-GB', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

  res.render('all_tickets', {
    reservations,
    today,
    title: 'All Tickets',
  });
});

// Checkout
app.get('/checkout/', requireAuth, (req, res) => {
  const username = req.session.user!.username;
  const result = dbStore.checkOutReservation(username);

  if (result.success) {
    flash(req, 'info', result.message);
  } else {
    flash(req, 'warning', result.message);
  }

  res.redirect('/');
});

// Fallback route
app.use((req, res) => {
  res.redirect('/');
});

// Start server
app.listen(PORT, HOST, () => {
  console.log(`Server running on http://${HOST}:${PORT}`);
});
