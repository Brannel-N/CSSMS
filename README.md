# CSSMS — Computer Studies Student Management System

CSSMS is a Django application for managing Computer Studies learners, teaching resources, assignments, practical lessons, attendance, and computer-laboratory inventory.

## Features

- Role-based accounts for administrators, teachers, students, and laboratory technicians.
- Student registration, classes, and streams.
- Learning material uploads and protected downloads.
- Assignment creation, student submissions, marking, and feedback.
- Practical activities, attendance, and computer-laboratory maintenance.
- Student-visible assignment and practical check-ins with an admin session log.
- Notifications, academic reports, and a dashboard.

## Requirements

- Python 3.10 or newer
- A modern browser

SQLite is used by default, so the app runs locally without a separate database server. MySQL can be selected with a `mysql+pymysql://` `DATABASE_URL`.

## Run on Windows

From the `CSSMS` folder:

```bat
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the `CSSMS` folder. For SQLite, add:

```text
SECRET_KEY=replace-this-with-a-long-random-secret
DATABASE_URL=sqlite:///db.sqlite3
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216
```

Then create the database schema and demo accounts:

```bat
python manage.py migrate
python manage.py init_demo
python manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000`.

## Demo accounts

| Role | Username | Password |
|---|---|---|
| Administrator | admin | Admin@12345 |
| Teacher | teacher | Teacher@123 |
| Student | student | Student@123 |
| Laboratory Technician | technician | Lab@12345 |

These are demo credentials. Change them and set a strong `SECRET_KEY` before using real student data or exposing the app to a network.

## Database configuration

SQLite is the default and stores data in `db.sqlite3`. To use MySQL, set `DATABASE_URL` in `.env`, for example:

```text
DATABASE_URL=mysql+pymysql://USER:PASSWORD@localhost:3306/DATABASE?charset=utf8mb4
```

Create the MySQL database and user before running `python manage.py migrate`. URL-encode special characters in passwords. Keep `.env` private and out of version control.

The Django app starts with a new schema. Existing data from another application is not automatically converted; export and migrate it separately.

## Uploads and production

Uploaded files, including profile photos, are stored in `uploads/`, with a 16 MB request limit. Users can change or remove their own JPEG, PNG, GIF, or WebP profile photo (up to 5 MB) from **My profile**. For production, use HTTPS and a production WSGI server, configure `DEBUG=False` and `ALLOWED_HOSTS`, rotate demo passwords and the secret key, and add backups, malware scanning, rate limiting, and per-student authorization checks.

## Preparing for a school deployment

The directory, assignments, materials, practicals, user accounts, and marking pages are paginated so a large school does not render every record in one response. Assignment submission totals use a database aggregate instead of loading all submission objects. MySQL connections are reused for up to 60 seconds by default; set `DB_CONN_MAX_AGE` to tune this against the database server's connection limit.

For 600+ learners, use MySQL rather than SQLite, run behind a production WSGI server (not `manage.py runserver`), and put static assets behind the web server or a CDN. Set a unique `SECRET_KEY`, `DEBUG=False`, and the real hostnames in `ALLOWED_HOSTS`; the application refuses the built-in development key in production mode. Set `SECURE_SSL_REDIRECT=true` when HTTPS is configured end-to-end. If TLS terminates at a trusted reverse proxy, set `TRUST_X_FORWARDED_PROTO=true` only when that proxy overwrites `X-Forwarded-Proto`. Set `SECURE_HSTS_SECONDS` only after HTTPS has been verified across the entire site; start with a short duration before considering a longer policy. If deploying multiple application instances, place uploads on shared object/file storage rather than instance-local disk. Configure automated database and upload backups and test restores.

Pagination and database indexes reduce avoidable work, but they do not prove capacity for a particular hosting plan. Run a concurrent load test against the intended database, web-server worker count, and storage before launch; capacity depends on those resources and the number of users active at the same time.
