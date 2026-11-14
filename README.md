# CampusFind 🔎

### Lost something? Find it here.

CampusFind is a web-based Lost and Found Management System designed to help college students report lost belongings, discover found items, and reconnect misplaced items with their rightful owners.

The platform provides a centralized place where students can report items, search listings, submit claims, and receive notifications.

**Live Website:** [CampusFind](https://YOUR-RENDER-URL.onrender.com)

---

## ✨ Features

### 👨‍🎓 Student Features
- Student registration and secure login.
- Report lost and found items.
- Upload item photographs.
- Browse available listings.
- Search and filter items by category and report type.
- View detailed item information.
- Submit claims for found belongings.
- Track claim status.
- Receive notifications about claim updates.

### 🛡️ Admin Features
- Dedicated admin dashboard.
- Manage student accounts.
- Review and manage reported items.
- Approve or reject claims.
- Monitor platform activity.

### 🔐 Security Features
- Password hashing.
- CSRF protection.
- Input validation.
- Secure session management.
- Image type and size validation.
- Rate limiting.
- Production security configuration.

---

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming |
| Flask | Web framework |
| HTML5 | Page structure |
| CSS3 | Styling and responsive design |
| JavaScript | Frontend interactions |
| Supabase PostgreSQL | Production database |
| SQLite | Local development database |
| Supabase Storage | Image storage |
| Gunicorn | Production WSGI server |
| Render | Cloud hosting |
| Git & GitHub | Version control |

---

## 🏗️ Architecture

CampusFind uses a Flask-based backend connected to a relational database.

- **Frontend:** HTML, CSS and JavaScript.
- **Backend:** Python and Flask.
- **Database:** Supabase PostgreSQL in production.
- **Image storage:** Private Supabase Storage bucket.
- **Hosting:** Render.

SQLite is supported for local development.

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd CampusFind
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate it:

**Windows:**
```bash
venv\Scripts\activate
```

**Linux / macOS:**
```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root.

Add the required configuration:

```env
CAMPUSFIND_ENV=development
SECRET_KEY=your-secret-key

# Database configuration
DATABASE_URL=

# Supabase configuration
SUPABASE_URL=your-supabase-project-url
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_BUCKET=campusfind-uploads
SUPABASE_SIGNED_URL_EXPIRY=3600
```

For local SQLite development, leave `DATABASE_URL` empty if the application is configured to use SQLite as its fallback.

Never commit your `.env` file or expose your Supabase service-role key.

### 5. Run the application

Use the application's configured Flask entry point. For the standard `app.py` setup:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

---

## ☁️ Deployment

CampusFind is deployed using Render and Supabase.

**Hosting:** Render  
**Database:** Supabase PostgreSQL  
**Image Storage:** Supabase Storage

Production deployment requires the appropriate environment variables to be configured securely in Render.

Typical Gunicorn start command:

```bash
gunicorn app:app
```

---

## 🔒 Environment & Security

- Keep credentials in environment variables.
- Never upload `.env` to GitHub.
- Never expose Supabase service-role credentials.
- Use HTTPS in production.
- Keep database backups.
- Restrict administrative access.

---

## 🎯 Project Objective

The objective of CampusFind is to make the lost-and-found process easier, faster, and more organized within educational institutions.

Instead of depending entirely on manual announcements or word of mouth, students can use one centralized platform to report and search for belongings.

---

## 🔮 Future Improvements

- Email notifications.
- QR-based item identification.
- AI-powered image matching.
- Smart item recommendations.
- Mobile application.
- Multi-college support.

---

## 👨‍💻 Author

**Shourya**

B.Tech Computer Science & Engineering Student

GitHub: [Shourya-dev29](https://github.com/Shourya-dev29)

---

## 📄 License

This project is available under the MIT License.

---

### Disclaimer

CampusFind is an independent student-developed project. It is not an official service or application of any college or university unless formally authorized.

---

⭐ If you find this project useful, consider giving the repository a star!
