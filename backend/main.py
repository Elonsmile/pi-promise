from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import Optional
import datetime, os, jwt, base64, logging, requests

# Configuration via environment variables
JWT_SECRET = os.getenv("JWT_SECRET", "change_this_secret")
JWT_ALGORITHM = "HS256"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./database.db")
PI_API_URL = os.getenv("PI_API_URL", "")  # e.g. https://api.pi.network/v1/userinfo
PI_API_KEY = os.getenv("PI_API_KEY", "")  # If required by Pi API
DEMO_PI_AUTH = os.getenv("DEMO_PI_AUTH", "1") == "1"  # allow demo fallback if real API not set

# Fraud detection thresholds (tune these)
MAX_AD_VIEWS_PER_12H = 5
MAX_AD_SKIPS_PER_12H = 2
ANOMALY_COIN_RATE_THRESHOLD = 2.0  # coins awarded vs expected multiplier to flag

# setup
logging.basicConfig(level=logging.INFO)
engine = create_engine(DATABASE_URL, echo=False)
app = FastAPI(title="PiPromise — Pi API Ready")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pi_name: str
    avatar_url: Optional[str] = None
    gender: Optional[str] = "unspecified"
    coins: int = 0
    last_mined_at: Optional[datetime.datetime] = None
    ads_viewed_window_start: Optional[datetime.datetime] = None
    ads_viewed_count: int = 0
    ad_skips_count: int = 0
    created_at: Optional[datetime.datetime] = Field(default_factory=datetime.datetime.utcnow)
    blocked: bool = False
    flagged: bool = False
    total_system_awarded: int = 0  # track coins that server awarded by rules

class Audit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    action: str
    detail: Optional[str] = None
    timestamp: Optional[datetime.datetime] = Field(default_factory=datetime.datetime.utcnow)

def init_db():
    SQLModel.metadata.create_all(engine)

@app.on_event("startup")
def startup():
    init_db()

def create_jwt(payload: dict, hours: int = 24):
    data = payload.copy(); data["exp"] = datetime.datetime.utcnow() + datetime.timedelta(hours=hours)
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception as e:
        return None

# Pi verification implementation:
# - If PI_API_URL and PI_API_KEY are provided, call the Pi API endpoint with the provided access_token/proof.
# - Expect a JSON response containing at least: { "pi_name": "...", "kyc_verified": true, "avatar_url": "...", "gender": "male" }
# - If Pi API isn't configured, fallback to demo mode where proof == "pi_demo" is accepted.
def verify_pi_user(pi_name: str, proof: str) -> Optional[dict]:
    """
    Returns user info dict on success: {"pi_name":..., "kyc_verified": True/False, "avatar_url":..., "gender":...}
    Returns None on verification failure.
    """
    # Demo fallback
    if DEMO_PI_AUTH and (proof == "pi_demo"):
        return {"pi_name": pi_name, "kyc_verified": True, "avatar_url": None, "gender": "unspecified"}
    # If PI_API_URL not configured, fail
    if not PI_API_URL:
        return None
    # Call Pi API
    try:
        headers = {"Content-Type": "application/json"}
        if PI_API_KEY:
            headers["Authorization"] = f"Bearer {PI_API_KEY}"
        payload = {"pi_name": pi_name, "proof": proof}
        resp = requests.post(PI_API_URL, json=payload, headers=headers, timeout=8)
        if resp.status_code != 200:
            logging.warning("Pi API returned status %s: %s", resp.status_code, resp.text)
            return None
        data = resp.json()
        # Expected fields check (adjust based on actual Pi API)
        pi = data.get("pi_name") or data.get("username") or pi_name
        kyc = data.get("kyc_verified") or data.get("kyc") or False
        avatar = data.get("avatar_url") or data.get("picture") or None
        gender = data.get("gender") or data.get("sex") or "unspecified"
        return {"pi_name": pi, "kyc_verified": bool(kyc), "avatar_url": avatar, "gender": gender}
    except Exception as e:
        logging.exception("Error calling Pi API: %s", e)
        return None

# Models
class PiAuthIn(BaseModel):
    pi_name: str
    proof: str  # signature / access_token provided by Pi wallet

# Auth endpoint using Pi auth: auto-creates profile if KYC verified
@app.post("/auth/pi")
def pi_auth(payload: PiAuthIn):
    info = verify_pi_user(payload.pi_name, payload.proof)
    if not info:
        raise HTTPException(status_code=401, detail="Pi verification failed. Check PI_API_URL/PI_API_KEY or provide valid proof.")
    if not info.get("kyc_verified"):
        raise HTTPException(status_code=403, detail="KYC not verified on Pi network. Access denied.")
    # create or get user
    with Session(engine) as s:
        user = s.exec(select(User).where(User.pi_name == info["pi_name"])).first()
        if not user:
            user = User(pi_name=info["pi_name"], avatar_url=info.get("avatar_url"), gender=info.get("gender"))
            s.add(user); s.commit(); s.refresh(user)
            audit(s, user.id, "create_user", "Created via Pi auth")
        token = create_jwt({"user_id": user.id, "pi_name": user.pi_name})
        audit(s, user.id, "auth", "Pi auth successful")
        return {"token": token, "user": {"pi_name": user.pi_name, "coins": user.coins, "avatar_url": user.avatar_url, "blocked": user.blocked}}

# helper to require user
def require_user(token: str):
    data = decode_jwt(token)
    if not data: raise HTTPException(status_code=401, detail="Invalid token")
    user_id = data.get("user_id")
    with Session(engine) as s:
        user = s.get(User, user_id)
        if not user: raise HTTPException(status_code=401, detail="User not found")
        if user.blocked: raise HTTPException(status_code=403, detail="User blocked due to fraud/abuse")
        return user

def audit(session: Session, user_id: int, action: str, detail: str = ""):
    a = Audit(user_id=user_id, action=action, detail=detail)
    session.add(a); session.commit()

# Mining endpoint (100 coins, 12-hour cooldown) with anti-fraud checks.
@app.post("/mine")
def mine(token: str, background_tasks: BackgroundTasks):
    user = require_user(token)
    now = datetime.datetime.utcnow()
    with Session(engine) as s:
        dbu = s.get(User, user.id)
        if dbu.last_mined_at and (now - dbu.last_mined_at).total_seconds() < 12*3600:
            rem = 12*3600 - (now - dbu.last_mined_at).total_seconds()
            raise HTTPException(status_code=400, detail=f"Cooldown active. Try again in {int(rem//60)} minutes.")
        # award
        dbu.coins += 100
        dbu.total_system_awarded += 100
        dbu.last_mined_at = now
        s.add(dbu); s.commit(); s.refresh(dbu)
        audit(s, dbu.id, "mine", "Awarded 100 coins")
        # schedule quick anomaly check
        background_tasks.add_task(run_quick_anomaly_check, dbu.id)
        return {"coins": dbu.coins, "message": "Mined 100 PiPromise coins."}

# View ad: +5 coins, max 5 per 12-hour window
@app.post("/view_ad")
def view_ad(token: str, background_tasks: BackgroundTasks):
    user = require_user(token)
    now = datetime.datetime.utcnow()
    with Session(engine) as s:
        dbu = s.get(User, user.id)
        # reset window if expired
        if not dbu.ads_viewed_window_start or (now - dbu.ads_viewed_window_start).total_seconds() > 12*3600:
            dbu.ads_viewed_window_start = now; dbu.ads_viewed_count = 0; dbu.ad_skips_count = 0
        if dbu.ads_viewed_count >= MAX_AD_VIEWS_PER_12H:
            raise HTTPException(status_code=400, detail="Ad view limit reached for this 12-hour window.")
        dbu.ads_viewed_count += 1
        dbu.coins += 5
        dbu.total_system_awarded += 5
        s.add(dbu); s.commit(); s.refresh(dbu)
        audit(s, dbu.id, "view_ad", f"Ad viewed. Count: {dbu.ads_viewed_count}")
        background_tasks.add_task(run_quick_anomaly_check, dbu.id)
        return {"coins": dbu.coins, "ads_viewed_count": dbu.ads_viewed_count}

@app.post("/skip_ad")
def skip_ad(token: str):
    user = require_user(token)
    now = datetime.datetime.utcnow()
    with Session(engine) as s:
        dbu = s.get(User, user.id)
        if not dbu.ads_viewed_window_start or (now - dbu.ads_viewed_window_start).total_seconds() > 12*3600:
            dbu.ads_viewed_window_start = now; dbu.ads_viewed_count = 0; dbu.ad_skips_count = 0
        if dbu.ad_skips_count >= MAX_AD_SKIPS_PER_12H:
            raise HTTPException(status_code=400, detail="Skip limit reached for this 12-hour window.")
        dbu.ad_skips_count += 1
        s.add(dbu); s.commit(); s.refresh(dbu)
        audit(s, dbu.id, "skip_ad", f"Skipped ad. Count: {dbu.ad_skips_count}")
        return {"ad_skips_count": dbu.ad_skips_count}

# Leaderboard and profile endpoints
@app.get("/leaderboard")
def leaderboard(limit: int = 50):
    with Session(engine) as s:
        rows = s.exec(select(User).order_by(User.coins.desc()).limit(limit)).all()
        return {"leaderboard": [{"pi_name": r.pi_name, "coins": r.coins, "avatar_url": r.avatar_url, "flagged": r.flagged} for r in rows]}

@app.get("/me")
def me(token: str):
    user = require_user(token)
    return {"pi_name": user.pi_name, "coins": user.coins, "avatar_url": user.avatar_url, "blocked": user.blocked, "flagged": user.flagged, "ads_viewed_count": user.ads_viewed_count}

# Admin: block user by pi_name (protect this endpoint in production)
@app.post("/admin/block")
def admin_block(pi_name: str):
    with Session(engine) as s:
        u = s.exec(select(User).where(User.pi_name == pi_name)).first()
        if not u: raise HTTPException(status_code=404, detail="User not found")
        u.blocked = True
        s.add(u); s.commit()
        audit(s, u.id, "admin_block", "Blocked by admin")
        return {"ok": True}

# Simple anomaly detection: checks if system-awarded coins greatly exceed expected given actions.
def run_quick_anomaly_check(user_id: int):
    with Session(engine) as s:
        u = s.get(User, user_id)
        if not u: return
        audits = s.exec(select(Audit).where(Audit.user_id == user_id)).all()
        expected = 0
        for a in audits:
            if a.action == "mine": expected += 100
            if a.action == "view_ad": expected += 5
        if expected == 0:
            if u.total_system_awarded > 0:
                u.flagged = True; s.add(u); s.commit(); audit(s, u.id, "flag", "awards without expected audits")
            return
        ratio = u.total_system_awarded / expected if expected>0 else 1.0
        if ratio > ANOMALY_COIN_RATE_THRESHOLD or u.total_system_awarded > expected + 1000:
            u.flagged = True
            s.add(u); s.commit(); audit(s, u.id, "flag", f"Anomaly detected. awarded={u.total_system_awarded}, expected={expected}, ratio={ratio:.2f}")
            if ratio > (ANOMALY_COIN_RATE_THRESHOLD * 2):
                u.blocked = True; s.add(u); s.commit(); audit(s, u.id, "auto_block", "Auto-block triggered by anomaly")

# Health endpoint
@app.get("/health")
def health():
    return {"status": "ok"}