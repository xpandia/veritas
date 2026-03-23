"""
Veritas — AI-Powered Decentralized Arbitration Backend

FastAPI server providing:
    - Case management API (CRUD, lifecycle transitions)
    - Evidence upload and management (file + metadata)
    - AI analysis integration (proxies to GenLayer contract)
    - Case timeline tracking (event log per dispute)
    - User authentication (JWT-based)
    - Notification system (in-app + webhook)
    - Analytics dashboard data
    - SQLite persistence via SQLAlchemy + aiosqlite
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, Boolean, create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv()

# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("veritas")

# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------

GENLAYER_RPC_URL = os.getenv("GENLAYER_RPC_URL", "http://localhost:4000/api")
CONTRACT_ADDRESS = os.getenv("ARBITRATION_CONTRACT_ADDRESS", "")

# JWT_SECRET MUST be set via environment variable in production.
# If not set, generate a random secret (safe for dev, but tokens won't survive restarts).
_jwt_env = os.getenv("JWT_SECRET", "")
if not _jwt_env:
    _jwt_env = secrets.token_urlsafe(64)
    logger.warning(
        "JWT_SECRET not set in environment — generated a random ephemeral secret. "
        "Set JWT_SECRET in your .env or environment for production use."
    )
JWT_SECRET: str = _jwt_env

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
MAX_FILE_SIZE_MB = 50
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./veritas.db")

# ---------------------------------------------------------------------------
#  Database Setup (SQLite via SQLAlchemy)
# ---------------------------------------------------------------------------

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class UserRow(Base):
    __tablename__ = "users"
    email = Column(String, primary_key=True, index=True)
    user_id = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    wallet_address = Column(String, nullable=False)
    created_at = Column(String, nullable=False)


class CaseRow(Base):
    __tablename__ = "cases"
    case_id = Column(String, primary_key=True, index=True)
    data = Column(Text, nullable=False)  # JSON blob


class EvidenceRow(Base):
    __tablename__ = "evidence"
    evidence_id = Column(String, primary_key=True)
    case_id = Column(String, index=True, nullable=False)
    data = Column(Text, nullable=False)  # JSON blob


class TimelineRow(Base):
    __tablename__ = "timeline"
    event_id = Column(String, primary_key=True)
    case_id = Column(String, index=True, nullable=False)
    data = Column(Text, nullable=False)


class NotificationRow(Base):
    __tablename__ = "notifications"
    notification_id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    is_read = Column(Boolean, default=False)
    data = Column(Text, nullable=False)


Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


# ---------------------------------------------------------------------------
#  DB-backed store helpers (drop-in replacements for the old in-memory dicts)
# ---------------------------------------------------------------------------

def db_get_user(email: str) -> dict | None:
    db = get_db()
    try:
        row = db.query(UserRow).filter(UserRow.email == email).first()
        if not row:
            return None
        return {
            "user_id": row.user_id,
            "email": row.email,
            "password_hash": row.password_hash,
            "display_name": row.display_name,
            "wallet_address": row.wallet_address,
            "created_at": row.created_at,
        }
    finally:
        db.close()


def db_put_user(user: dict) -> None:
    db = get_db()
    try:
        row = UserRow(
            email=user["email"],
            user_id=user["user_id"],
            password_hash=user["password_hash"],
            display_name=user["display_name"],
            wallet_address=user["wallet_address"],
            created_at=user["created_at"],
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def db_all_users() -> list[dict]:
    db = get_db()
    try:
        rows = db.query(UserRow).all()
        return [
            {
                "user_id": r.user_id,
                "email": r.email,
                "password_hash": r.password_hash,
                "display_name": r.display_name,
                "wallet_address": r.wallet_address,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    finally:
        db.close()


def db_get_case(case_id: str) -> dict | None:
    db = get_db()
    try:
        row = db.query(CaseRow).filter(CaseRow.case_id == case_id).first()
        return json.loads(row.data) if row else None
    finally:
        db.close()


def db_put_case(case: dict) -> None:
    db = get_db()
    try:
        existing = db.query(CaseRow).filter(CaseRow.case_id == case["case_id"]).first()
        if existing:
            existing.data = json.dumps(case)
        else:
            db.add(CaseRow(case_id=case["case_id"], data=json.dumps(case)))
        db.commit()
    finally:
        db.close()


def db_all_cases() -> list[dict]:
    db = get_db()
    try:
        rows = db.query(CaseRow).all()
        return [json.loads(r.data) for r in rows]
    finally:
        db.close()


def db_get_evidence(case_id: str) -> list[dict]:
    db = get_db()
    try:
        rows = db.query(EvidenceRow).filter(EvidenceRow.case_id == case_id).all()
        return [json.loads(r.data) for r in rows]
    finally:
        db.close()


def db_put_evidence(record: dict) -> None:
    db = get_db()
    try:
        db.add(EvidenceRow(
            evidence_id=record["evidence_id"],
            case_id=record["case_id"],
            data=json.dumps(record),
        ))
        db.commit()
    finally:
        db.close()


def db_all_evidence() -> dict[str, list[dict]]:
    db = get_db()
    try:
        rows = db.query(EvidenceRow).all()
        result: dict[str, list[dict]] = {}
        for r in rows:
            d = json.loads(r.data)
            result.setdefault(r.case_id, []).append(d)
        return result
    finally:
        db.close()


def db_add_timeline_event(event: dict) -> None:
    db = get_db()
    try:
        db.add(TimelineRow(
            event_id=event["event_id"],
            case_id=event["case_id"],
            data=json.dumps(event),
        ))
        db.commit()
    finally:
        db.close()


def db_get_timeline(case_id: str) -> list[dict]:
    db = get_db()
    try:
        rows = db.query(TimelineRow).filter(TimelineRow.case_id == case_id).all()
        return [json.loads(r.data) for r in rows]
    finally:
        db.close()


def db_add_notification(notif: dict) -> None:
    db = get_db()
    try:
        db.add(NotificationRow(
            notification_id=notif["notification_id"],
            user_id=notif["user_id"],
            is_read=notif["read"],
            data=json.dumps(notif),
        ))
        db.commit()
    finally:
        db.close()


def db_get_notifications(user_id: str) -> list[dict]:
    db = get_db()
    try:
        rows = db.query(NotificationRow).filter(NotificationRow.user_id == user_id).all()
        return [json.loads(r.data) for r in rows]
    finally:
        db.close()


def db_mark_notifications_read(user_id: str, notification_ids: list[str]) -> int:
    db = get_db()
    try:
        marked = 0
        rows = (
            db.query(NotificationRow)
            .filter(NotificationRow.user_id == user_id)
            .filter(NotificationRow.notification_id.in_(notification_ids))
            .all()
        )
        for row in rows:
            row.is_read = True
            data = json.loads(row.data)
            data["read"] = True
            row.data = json.dumps(data)
            marked += 1
        db.commit()
        return marked
    finally:
        db.close()

# ---------------------------------------------------------------------------
#  Auth Utilities
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=JWT_EXPIRE_HOURS))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Extract and validate the current user from the JWT bearer token."""
    payload = decode_token(credentials.credentials)
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="User not found")
    user = db_get_user(email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ---------------------------------------------------------------------------
#  GenLayer RPC Client
# ---------------------------------------------------------------------------

async def call_contract(method: str, params: list[Any]) -> dict:
    """
    Call a GenLayer intelligent contract method via JSON-RPC.

    Maps to the deployed Arbitration contract on the GenLayer testnet.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "call_contract_function",
        "params": {
            "contract_address": CONTRACT_ADDRESS,
            "function_name": method,
            "function_args": params,
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(GENLAYER_RPC_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    if "error" in data:
        raise HTTPException(
            status_code=502,
            detail=f"GenLayer contract error: {data['error']}",
        )
    return data.get("result", {})


async def send_contract_transaction(method: str, params: list[Any], sender: str) -> dict:
    """
    Send a state-changing transaction to the GenLayer contract.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "send_transaction",
        "params": {
            "contract_address": CONTRACT_ADDRESS,
            "function_name": method,
            "function_args": params,
            "sender_address": sender,
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(GENLAYER_RPC_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    if "error" in data:
        raise HTTPException(
            status_code=502,
            detail=f"GenLayer transaction error: {data['error']}",
        )
    return data.get("result", {})


# ---------------------------------------------------------------------------
#  Block Number Helper
# ---------------------------------------------------------------------------

async def get_current_block_number() -> int:
    """
    Fetch the current block number from the GenLayer RPC node.

    Falls back to 0 if the RPC is unreachable (e.g. during local development).
    This replaces the previous hack of using int(time.time()) as a block number.
    """
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_blockNumber",
            "params": [],
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(GENLAYER_RPC_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
        result = data.get("result", "0x0")
        if isinstance(result, str) and result.startswith("0x"):
            return int(result, 16)
        return int(result)
    except Exception:
        logger.warning("Could not fetch block number from GenLayer RPC; returning 0")
        return 0


# ---------------------------------------------------------------------------
#  Timeline Utility
# ---------------------------------------------------------------------------

def add_timeline_event(
    case_id: str,
    event_type: str,
    description: str,
    actor: str = "",
    metadata: dict | None = None,
) -> dict:
    """Append an event to a case's timeline (persisted to SQLite)."""
    event = {
        "event_id": str(uuid.uuid4()),
        "case_id": case_id,
        "event_type": event_type,
        "description": description,
        "actor": actor,
        "metadata": metadata or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    db_add_timeline_event(event)
    return event


def add_notification(
    user_id: str,
    title: str,
    message: str,
    case_id: str = "",
    notification_type: str = "info",
) -> dict:
    """Create a notification for a user (persisted to SQLite)."""
    notif = {
        "notification_id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": title,
        "message": message,
        "case_id": case_id,
        "type": notification_type,
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db_add_notification(notif)
    return notif


# ---------------------------------------------------------------------------
#  Pydantic Models
# ---------------------------------------------------------------------------

class UserRegister(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str
    wallet_address: str


class UserLogin(BaseModel):
    email: str
    password: str


class UserProfile(BaseModel):
    user_id: str
    email: str
    display_name: str
    wallet_address: str
    created_at: str


class DisputeCategory(str, Enum):
    CONTRACT_BREACH = "contract_breach"
    IP_INFRINGEMENT = "ip_infringement"
    FRAUD = "fraud"
    SERVICE_DISPUTE = "service_dispute"
    OTHER = "other"


class CaseCreate(BaseModel):
    respondent_address: str
    category: DisputeCategory
    title: str = Field(max_length=200)
    description: str = Field(max_length=5000)
    escrow_amount: int = Field(ge=0)
    filing_fee: int = Field(ge=100)


class EvidenceSubmit(BaseModel):
    evidence_type: str = Field(
        pattern="^(document|communication|transaction|testimony|expert_report)$"
    )
    description: str = Field(max_length=2000)
    metadata: dict = Field(default_factory=dict)


class AppealCreate(BaseModel):
    grounds: str = Field(max_length=5000)
    appeal_fee: int = Field(ge=0)
    new_evidence_hashes: list[str] = Field(default_factory=list)


class NotificationMarkRead(BaseModel):
    notification_ids: list[str]


# ---------------------------------------------------------------------------
#  Application Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


# ---------------------------------------------------------------------------
#  FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Veritas — AI-Powered Decentralized Arbitration",
    description=(
        "Backend API for the Veritas decentralized arbitration platform, "
        "built on GenLayer for the Testnet Bradbury hackathon."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================================================================
#  AUTH ENDPOINTS
# ===================================================================

@app.post("/api/auth/register", tags=["Auth"])
async def register(body: UserRegister):
    """Register a new user account."""
    if db_get_user(body.email):
        raise HTTPException(status_code=409, detail="Email already registered")

    user_id = str(uuid.uuid4())
    user = {
        "user_id": user_id,
        "email": body.email,
        "password_hash": hash_password(body.password),
        "display_name": body.display_name,
        "wallet_address": body.wallet_address,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db_put_user(user)

    token = create_access_token({"sub": body.email, "uid": user_id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": user_id,
            "email": body.email,
            "display_name": body.display_name,
            "wallet_address": body.wallet_address,
        },
    }


@app.post("/api/auth/login", tags=["Auth"])
async def login(body: UserLogin):
    """Authenticate and receive a JWT token."""
    user = db_get_user(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": body.email, "uid": user["user_id"]})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "wallet_address": user["wallet_address"],
        },
    }


@app.get("/api/auth/me", tags=["Auth"])
async def get_me(user: dict = Depends(get_current_user)):
    """Get the authenticated user's profile."""
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "wallet_address": user["wallet_address"],
        "created_at": user["created_at"],
    }


# ===================================================================
#  CASE MANAGEMENT
# ===================================================================

@app.post("/api/cases", tags=["Cases"], status_code=201)
async def create_case(body: CaseCreate, user: dict = Depends(get_current_user)):
    """
    File a new arbitration case.

    This creates a local case record and submits the dispute to the
    GenLayer Arbitration contract.
    """
    case_id = str(uuid.uuid4())
    block_number = await get_current_block_number()

    # Submit to on-chain contract
    contract_result = await send_contract_transaction(
        "file_dispute",
        [
            user["wallet_address"],
            body.respondent_address,
            body.category.value,
            body.title,
            body.description,
            body.escrow_amount,
            body.filing_fee,
            block_number,
        ],
        sender=user["wallet_address"],
    )

    case = {
        "case_id": case_id,
        "on_chain_dispute_id": contract_result.get("dispute_id", ""),
        "claimant_id": user["user_id"],
        "claimant_address": user["wallet_address"],
        "respondent_address": body.respondent_address,
        "category": body.category.value,
        "title": body.title,
        "description": body.description,
        "status": "FILED",
        "escrow_amount": body.escrow_amount,
        "filing_fee": body.filing_fee,
        "current_round": 1,
        "appeal_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "contract_result": contract_result,
    }
    db_put_case(case)

    add_timeline_event(
        case_id, "CASE_FILED", f"Case filed by {user['display_name']}", actor=user["user_id"]
    )

    # Notify respondent if they have an account
    for u in db_all_users():
        if u["wallet_address"] == body.respondent_address:
            add_notification(
                u["user_id"],
                "New Case Filed Against You",
                f"A {body.category.value} dispute has been filed: {body.title}",
                case_id=case_id,
                notification_type="alert",
            )

    return case


@app.get("/api/cases", tags=["Cases"])
async def list_cases(
    status_filter: str | None = Query(None, alias="status"),
    category: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """
    List cases for the authenticated user.

    Returns cases where the user is either claimant or respondent.
    Supports filtering by status and category, with pagination.
    """
    user_address = user["wallet_address"]
    user_id = user["user_id"]

    filtered = []
    for c in db_all_cases():
        # User must be a party
        if c["claimant_address"] != user_address and c["respondent_address"] != user_address:
            if c["claimant_id"] != user_id:
                continue

        if status_filter and c["status"] != status_filter:
            continue
        if category and c["category"] != category:
            continue
        filtered.append(c)

    # Sort by creation date descending
    filtered.sort(key=lambda x: x["created_at"], reverse=True)

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "cases": filtered[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@app.get("/api/cases/{case_id}", tags=["Cases"])
async def get_case(case_id: str, user: dict = Depends(get_current_user)):
    """Get full details for a specific case."""
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Fetch latest on-chain state if we have a dispute ID
    on_chain_data = {}
    if case.get("on_chain_dispute_id"):
        try:
            on_chain_data = await call_contract(
                "get_dispute", [case["on_chain_dispute_id"]]
            )
        except Exception:
            on_chain_data = {"error": "Could not fetch on-chain data"}

    return {
        **case,
        "evidence_count": len(db_get_evidence(case_id)),
        "timeline_count": len(db_get_timeline(case_id)),
        "on_chain_state": on_chain_data,
    }


# ===================================================================
#  EVIDENCE MANAGEMENT
# ===================================================================

@app.post("/api/cases/{case_id}/evidence", tags=["Evidence"], status_code=201)
async def upload_evidence(
    case_id: str,
    evidence_type: str,
    description: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """
    Upload evidence for a case.

    The file is stored locally and its SHA-256 hash is submitted to the
    on-chain contract as a content-addressed reference.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case["status"] not in ("FILED", "EVIDENCE_SUBMISSION", "APPEAL"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit evidence in status: {case['status']}",
        )

    # Validate file size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_SIZE_MB}MB limit")

    # Compute content hash
    file_hash = hashlib.sha256(contents).hexdigest()

    # Store file
    case_upload_dir = UPLOAD_DIR / case_id
    case_upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = case_upload_dir / f"{file_hash}_{file.filename}"
    file_path.write_bytes(contents)

    # Submit to on-chain contract
    block_number = await get_current_block_number()
    contract_result = {}
    if case.get("on_chain_dispute_id"):
        try:
            contract_result = await send_contract_transaction(
                "submit_evidence",
                [
                    case["on_chain_dispute_id"],
                    user["wallet_address"],
                    evidence_type,
                    file_hash,
                    description,
                    {},
                    block_number,
                ],
                sender=user["wallet_address"],
            )
        except Exception as e:
            logger.error("Contract call submit_evidence failed: %s", e)
            contract_result = {"error": str(e)}

    evidence_record = {
        "evidence_id": str(uuid.uuid4()),
        "case_id": case_id,
        "submitter_id": user["user_id"],
        "submitter_address": user["wallet_address"],
        "evidence_type": evidence_type,
        "description": description,
        "file_name": file.filename,
        "file_hash": file_hash,
        "file_size": len(contents),
        "content_type": file.content_type,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "contract_result": contract_result,
    }
    db_put_evidence(evidence_record)

    # Update case status
    if case["status"] == "FILED":
        case["status"] = "EVIDENCE_SUBMISSION"
        case["updated_at"] = datetime.now(timezone.utc).isoformat()
        db_put_case(case)

    add_timeline_event(
        case_id,
        "EVIDENCE_SUBMITTED",
        f"{user['display_name']} submitted {evidence_type} evidence: {description[:100]}",
        actor=user["user_id"],
        metadata={"evidence_id": evidence_record["evidence_id"], "file_hash": file_hash},
    )

    return evidence_record


@app.get("/api/cases/{case_id}/evidence", tags=["Evidence"])
async def list_evidence(case_id: str, user: dict = Depends(get_current_user)):
    """List all evidence submitted for a case."""
    if not db_get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    evidence = db_get_evidence(case_id)
    return {
        "case_id": case_id,
        "evidence": evidence,
        "total": len(evidence),
    }


@app.get("/api/cases/{case_id}/evidence/{evidence_id}", tags=["Evidence"])
async def get_evidence(case_id: str, evidence_id: str, user: dict = Depends(get_current_user)):
    """Get details for a specific piece of evidence."""
    if not db_get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    for ev in db_get_evidence(case_id):
        if ev["evidence_id"] == evidence_id:
            return ev

    raise HTTPException(status_code=404, detail="Evidence not found")


# ===================================================================
#  AI ANALYSIS
# ===================================================================

@app.post("/api/cases/{case_id}/analyze", tags=["AI Analysis"])
async def trigger_analysis(case_id: str, user: dict = Depends(get_current_user)):
    """
    Trigger AI-powered evidence analysis via the GenLayer contract.

    This invokes the equivalence principle on-chain: every validator
    independently queries the LLM and results are compared for consensus.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case["status"] not in ("EVIDENCE_SUBMISSION", "APPEAL"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot analyze evidence in status: {case['status']}",
        )

    if not case.get("on_chain_dispute_id"):
        raise HTTPException(status_code=400, detail="No on-chain dispute linked")

    result = await send_contract_transaction(
        "analyze_evidence",
        [case["on_chain_dispute_id"]],
        sender=user["wallet_address"],
    )

    add_timeline_event(
        case_id,
        "AI_ANALYSIS",
        f"AI evidence analysis triggered for round {case.get('current_round', 1)}",
        actor=user["user_id"],
        metadata={"analysis_result": result},
    )

    # Notify both parties
    add_notification(
        user["user_id"],
        "AI Analysis Complete",
        f"Evidence analysis for case '{case['title']}' is ready.",
        case_id=case_id,
    )

    return {
        "case_id": case_id,
        "analysis": result,
        "round": case.get("current_round", 1),
    }


@app.post("/api/cases/{case_id}/deliberate", tags=["AI Analysis"])
async def advance_deliberation(case_id: str, user: dict = Depends(get_current_user)):
    """
    Advance the case to the next deliberation round.

    After max rounds, this triggers the final verdict.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    result = await send_contract_transaction(
        "advance_deliberation",
        [case["on_chain_dispute_id"]],
        sender=user["wallet_address"],
    )

    # Update local state
    case["current_round"] = result.get("current_round", case["current_round"])
    new_status = result.get("status", case["status"])
    case["status"] = new_status
    case["updated_at"] = datetime.now(timezone.utc).isoformat()
    db_put_case(case)

    add_timeline_event(
        case_id,
        "DELIBERATION_ADVANCED",
        f"Deliberation advanced to round {case['current_round']}",
        actor=user["user_id"],
        metadata=result,
    )

    return {"case_id": case_id, **result}


@app.post("/api/cases/{case_id}/verdict", tags=["AI Analysis"])
async def request_verdict(case_id: str, user: dict = Depends(get_current_user)):
    """
    Request the final AI-powered verdict from the GenLayer contract.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    result = await send_contract_transaction(
        "render_verdict",
        [case["on_chain_dispute_id"]],
        sender=user["wallet_address"],
    )

    case["status"] = "VERDICT"
    case["updated_at"] = datetime.now(timezone.utc).isoformat()
    db_put_case(case)

    add_timeline_event(
        case_id, "VERDICT_RENDERED", "Final verdict has been rendered", actor="system", metadata=result
    )

    # Notify both parties
    for u in db_all_users():
        if u["wallet_address"] in (case["claimant_address"], case["respondent_address"]):
            add_notification(
                u["user_id"],
                "Verdict Rendered",
                f"The verdict for '{case['title']}' has been delivered.",
                case_id=case_id,
                notification_type="alert",
            )

    return {"case_id": case_id, **result}


# ===================================================================
#  APPEALS
# ===================================================================

@app.post("/api/cases/{case_id}/appeal", tags=["Appeals"], status_code=201)
async def file_appeal(
    case_id: str,
    body: AppealCreate,
    user: dict = Depends(get_current_user),
):
    """
    File an appeal against a rendered verdict.

    Appeals reset deliberation and allow new evidence submission.
    Each successive appeal requires a higher fee.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case["status"] != "VERDICT":
        raise HTTPException(status_code=400, detail="Can only appeal a rendered verdict")

    result = await send_contract_transaction(
        "file_appeal",
        [
            case["on_chain_dispute_id"],
            user["wallet_address"],
            body.grounds,
            body.new_evidence_hashes,
            body.appeal_fee,
        ],
        sender=user["wallet_address"],
    )

    case["status"] = "APPEAL"
    case["appeal_count"] = result.get("appeal_number", case["appeal_count"] + 1)
    case["current_round"] = 1
    case["updated_at"] = datetime.now(timezone.utc).isoformat()
    db_put_case(case)

    add_timeline_event(
        case_id,
        "APPEAL_FILED",
        f"Appeal #{case['appeal_count']} filed: {body.grounds[:100]}",
        actor=user["user_id"],
        metadata=result,
    )

    return {"case_id": case_id, **result}


# ===================================================================
#  RESOLUTION & ESCROW
# ===================================================================

@app.post("/api/cases/{case_id}/resolve", tags=["Resolution"])
async def resolve_case(case_id: str, user: dict = Depends(get_current_user)):
    """
    Finalize the case and distribute escrowed funds per the verdict.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    block_number = await get_current_block_number()

    result = await send_contract_transaction(
        "resolve_and_distribute",
        [case["on_chain_dispute_id"], block_number],
        sender=user["wallet_address"],
    )

    case["status"] = "RESOLVED"
    case["updated_at"] = datetime.now(timezone.utc).isoformat()
    db_put_case(case)

    add_timeline_event(
        case_id, "CASE_RESOLVED", "Case resolved and escrow distributed", actor="system", metadata=result
    )

    return {"case_id": case_id, **result}


@app.get("/api/cases/{case_id}/escrow", tags=["Resolution"])
async def get_escrow(case_id: str, user: dict = Depends(get_current_user)):
    """Query escrow balance for a case."""
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if not case.get("on_chain_dispute_id"):
        return {"case_id": case_id, "escrow_balance": case.get("escrow_amount", 0)}

    result = await call_contract("get_escrow_balance", [case["on_chain_dispute_id"]])
    return {"case_id": case_id, **result}


# ===================================================================
#  TIMELINE
# ===================================================================

@app.get("/api/cases/{case_id}/timeline", tags=["Timeline"])
async def get_timeline(case_id: str, user: dict = Depends(get_current_user)):
    """
    Get the full timeline of events for a case.

    The timeline provides a chronological audit trail of every action
    taken on the case: filing, evidence submissions, analysis rounds,
    verdicts, appeals, and resolution.
    """
    if not db_get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    events = db_get_timeline(case_id)
    return {
        "case_id": case_id,
        "events": events,
        "total": len(events),
    }


# ===================================================================
#  NOTIFICATIONS
# ===================================================================

@app.get("/api/notifications", tags=["Notifications"])
async def get_notifications(
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get notifications for the authenticated user."""
    all_notifs = db_get_notifications(user["user_id"])

    if unread_only:
        all_notifs = [n for n in all_notifs if not n["read"]]

    # Sort newest first
    all_notifs.sort(key=lambda x: x["created_at"], reverse=True)

    total = len(all_notifs)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "notifications": all_notifs[start:end],
        "total": total,
        "unread_count": sum(1 for n in db_get_notifications(user["user_id"]) if not n["read"]),
        "page": page,
        "page_size": page_size,
    }


@app.patch("/api/notifications/read", tags=["Notifications"])
async def mark_notifications_read(
    body: NotificationMarkRead,
    user: dict = Depends(get_current_user),
):
    """Mark specific notifications as read."""
    marked = db_mark_notifications_read(user["user_id"], body.notification_ids)
    return {"marked_read": marked}


# ===================================================================
#  REPUTATION
# ===================================================================

@app.get("/api/reputation/{wallet_address}", tags=["Reputation"])
async def get_reputation(wallet_address: str):
    """
    Get the on-chain reputation score for a wallet address.

    Reputation is computed from dispute outcomes, evidence quality,
    compliance history, and appeal track record.
    """
    try:
        result = await call_contract("get_reputation", [wallet_address])
        return result
    except Exception:
        # Return default reputation if contract call fails
        return {
            "address": wallet_address,
            "score": 500,
            "cases_filed": 0,
            "cases_responded": 0,
            "cases_won": 0,
            "cases_lost": 0,
            "compliance_score": 100,
            "message": "No on-chain reputation found; showing defaults.",
        }


# ===================================================================
#  ANALYTICS DASHBOARD
# ===================================================================

@app.get("/api/analytics/overview", tags=["Analytics"])
async def analytics_overview(user: dict = Depends(get_current_user)):
    """
    Get platform-wide analytics for the dashboard.

    Includes dispute counts by status/category, escrow totals,
    resolution rates, and average timelines.
    """
    all_cases = db_all_cases()
    total = len(all_cases)
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    total_escrow = 0
    resolved_cases = []

    for c in all_cases:
        st = c["status"]
        by_status[st] = by_status.get(st, 0) + 1
        cat = c["category"]
        by_category[cat] = by_category.get(cat, 0) + 1
        total_escrow += c.get("escrow_amount", 0)
        if st == "RESOLVED":
            resolved_cases.append(c)

    resolution_rate = (len(resolved_cases) / total * 100) if total > 0 else 0

    # Fetch on-chain stats if available
    on_chain_stats = {}
    try:
        on_chain_stats = await call_contract("get_platform_stats", [])
    except Exception:
        pass

    return {
        "total_cases": total,
        "cases_by_status": by_status,
        "cases_by_category": by_category,
        "total_escrow_value": total_escrow,
        "resolution_rate_pct": round(resolution_rate, 2),
        "resolved_count": len(resolved_cases),
        "active_count": total - len(resolved_cases),
        "on_chain_stats": on_chain_stats,
    }


@app.get("/api/analytics/user", tags=["Analytics"])
async def analytics_user(user: dict = Depends(get_current_user)):
    """
    Get analytics specific to the authenticated user.

    Covers their cases filed/responded, win/loss record,
    evidence submission count, and reputation trajectory.
    """
    user_address = user["wallet_address"]
    user_id = user["user_id"]

    filed = 0
    responded = 0
    won = 0
    lost = 0
    active = 0

    for c in db_all_cases():
        if c["claimant_address"] == user_address or c["claimant_id"] == user_id:
            filed += 1
            if c["status"] == "RESOLVED":
                # Simplified: check if claimant won
                won += 1  # Would check verdict in production
            elif c["status"] not in ("RESOLVED", "DISMISSED"):
                active += 1
        elif c["respondent_address"] == user_address:
            responded += 1

    all_evidence = db_all_evidence()
    evidence_count = sum(
        len([e for e in evs if e["submitter_id"] == user_id])
        for evs in all_evidence.values()
    )

    reputation = {}
    try:
        reputation = await call_contract("get_reputation", [user_address])
    except Exception:
        reputation = {"score": 500, "compliance_score": 100}

    return {
        "user_id": user_id,
        "cases_filed": filed,
        "cases_responded": responded,
        "cases_won": won,
        "cases_lost": lost,
        "active_cases": active,
        "total_evidence_submitted": evidence_count,
        "reputation": reputation,
    }


@app.get("/api/analytics/categories", tags=["Analytics"])
async def analytics_categories(user: dict = Depends(get_current_user)):
    """
    Get dispute distribution and outcome data grouped by category.
    """
    categories: dict[str, dict] = {}

    for c in db_all_cases():
        cat = c["category"]
        if cat not in categories:
            categories[cat] = {
                "category": cat,
                "total": 0,
                "resolved": 0,
                "active": 0,
                "total_escrow": 0,
                "avg_rounds": 0,
                "appeal_rate": 0,
            }
        entry = categories[cat]
        entry["total"] += 1
        entry["total_escrow"] += c.get("escrow_amount", 0)
        if c["status"] == "RESOLVED":
            entry["resolved"] += 1
        else:
            entry["active"] += 1

    # Compute averages
    for entry in categories.values():
        if entry["total"] > 0:
            entry["resolution_rate_pct"] = round(entry["resolved"] / entry["total"] * 100, 2)

    return {"categories": list(categories.values())}


# ===================================================================
#  HEALTH
# ===================================================================

@app.get("/api/health", tags=["System"])
async def health():
    """Health check endpoint."""
    genlayer_status = "unknown"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(GENLAYER_RPC_URL.replace("/api", "/health"))
            genlayer_status = "connected" if resp.status_code == 200 else "unreachable"
    except Exception:
        genlayer_status = "unreachable"

    return {
        "status": "healthy",
        "version": "1.0.0",
        "genlayer_rpc": genlayer_status,
        "contract_address": CONTRACT_ADDRESS or "not configured",
        "total_cases": len(db_all_cases()),
        "total_users": len(db_all_users()),
    }


# ---------------------------------------------------------------------------
#  Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
