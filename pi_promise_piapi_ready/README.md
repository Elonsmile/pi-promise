PiPromise — Pi API ready package

How to use:
1. Set environment variables for backend:
   - JWT_SECRET (strong secret)
   - DATABASE_URL (e.g., sqlite:///./database.db or Postgres URL)
   - PI_API_URL (the Pi-provided server-side verification endpoint that accepts {pi_name, proof} POST and returns JSON with kyc_verified)
   - PI_API_KEY (if Pi requires a key)

Example .env:
JWT_SECRET=your_strong_secret
DATABASE_URL=sqlite:///./database.db
PI_API_URL=https://api.pi.network/v1/verify_user
PI_API_KEY=your_pi_api_key_here
DEMO_PI_AUTH=0  # set to 0 in production to disable demo mode

2. Start backend:
   cd backend
   pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000

3. Frontend:
   cd frontend
   npm install
   npm run dev

Security & Notes:
- The backend expects the Pi API to return JSON fields: pi_name (or username), kyc_verified (boolean), avatar_url, gender. If Pi's API differs, adjust verify_pi_user accordingly.
- All reward awarding and limits are enforced server-side.
- Audit table stores actions for monitoring. Configure logs/alerts for flagged users.
- Admin endpoint /admin/block allows blocking a user by pi_name; protect this endpoint behind admin auth in production.