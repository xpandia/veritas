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

def seed_demo_data():
    """Seed the database with demo users, cases, evidence, and timeline events."""
    # Check if already seeded
    if db_all_users():
        return

    logger.info("Seeding demo data...")

    # --- Demo Users ---
    user1 = {
        "user_id": "usr-demo-alice-001",
        "email": "alice@veritas.legal",
        "password_hash": hash_password("demo1234"),
        "display_name": "Alice Montoya",
        "wallet_address": "0xAlice0001aaBBccDDeeFF00112233445566778899",
        "created_at": "2026-02-15T09:00:00+00:00",
    }
    user2 = {
        "user_id": "usr-demo-bob-002",
        "email": "bob@veritas.legal",
        "password_hash": hash_password("demo1234"),
        "display_name": "Roberto Vega",
        "wallet_address": "0xBob00002aaBBccDDeeFF00112233445566778899",
        "created_at": "2026-02-20T14:30:00+00:00",
    }
    db_put_user(user1)
    db_put_user(user2)

    now = datetime.now(timezone.utc)

    # --- Case 1: FILED (recent) ---
    case1_id = "case-demo-001"
    case1 = {
        "case_id": case1_id,
        "on_chain_dispute_id": "gl-dispute-0x7a1",
        "claimant_id": user1["user_id"],
        "claimant_address": user1["wallet_address"],
        "claimant_name": user1["display_name"],
        "respondent_address": "0xResp0003aaBBccDDeeFF00112233445566778899",
        "respondent_name": "TechNova Solutions S.A.",
        "category": "contract_breach",
        "title": "Incumplimiento de Contrato SaaS — Entrega de Plataforma",
        "description": (
            "El demandado se comprometio contractualmente a entregar una plataforma SaaS "
            "de gestion de inventario antes del 1 de enero de 2026. A la fecha, la plataforma "
            "presenta fallos criticos en los modulos de facturacion y reportes, incumpliendo "
            "los hitos del contrato marco. Se reclaman USD 45,000 correspondientes al 60%% "
            "del anticipo pagado mas danos por lucro cesante."
        ),
        "status": "FILED",
        "escrow_amount": 45000,
        "filing_fee": 500,
        "current_round": 1,
        "appeal_count": 0,
        "created_at": (now - timedelta(days=2)).isoformat(),
        "updated_at": (now - timedelta(days=2)).isoformat(),
        "contract_result": {"dispute_id": "gl-dispute-0x7a1", "tx_hash": "0xabc123..."},
    }

    # --- Case 2: DELIBERATION (mid-process) ---
    case2_id = "case-demo-002"
    case2 = {
        "case_id": case2_id,
        "on_chain_dispute_id": "gl-dispute-0x7a2",
        "claimant_id": user2["user_id"],
        "claimant_address": user2["wallet_address"],
        "claimant_name": user2["display_name"],
        "respondent_address": user1["wallet_address"],
        "respondent_name": user1["display_name"],
        "category": "ip_infringement",
        "title": "Infraccion de Propiedad Intelectual — Algoritmo de ML",
        "description": (
            "El demandante desarrollo un algoritmo propietario de machine learning para "
            "optimizacion de cadena de suministro, protegido bajo acuerdo de confidencialidad. "
            "El demandado implemento un sistema sustancialmente identico en su producto "
            "comercial sin autorizacion ni compensacion. Se solicita cesacion de uso e "
            "indemnizacion de USD 120,000 por danos y perjuicios."
        ),
        "status": "DELIBERATION",
        "escrow_amount": 120000,
        "filing_fee": 1200,
        "current_round": 2,
        "appeal_count": 0,
        "created_at": (now - timedelta(days=14)).isoformat(),
        "updated_at": (now - timedelta(days=1)).isoformat(),
        "contract_result": {"dispute_id": "gl-dispute-0x7a2", "tx_hash": "0xdef456..."},
        "ai_analysis": {
            "strengths_claimant": [
                "Contrato NDA firmado por ambas partes con fecha anterior al producto del demandado.",
                "Analisis de codigo muestra un 87%% de similitud estructural entre algoritmos.",
                "Registro de propiedad intelectual ante autoridad competente.",
            ],
            "weaknesses_claimant": [
                "Parte del algoritmo utiliza librerias open-source de uso comun.",
                "No se demostro acceso directo al repositorio privado.",
            ],
            "strengths_respondent": [
                "El demandado argumento desarrollo independiente con equipo propio.",
                "Timeline de commits en su repositorio comienza antes de la relacion comercial.",
            ],
            "weaknesses_respondent": [
                "Tres ingenieros del equipo del demandado trabajaron previamente con el demandante.",
                "No se presento documentacion de diseno independiente.",
            ],
            "preliminary_assessment": "El peso probatorio favorece al demandante en un 68%%. La evidencia de similitud estructural es significativa y el NDA establece restricciones claras. Sin embargo, la defensa de desarrollo independiente tiene merito parcial.",
            "confidence": 0.72,
            "deliberation_rounds": [
                {
                    "round": 1,
                    "summary": "Analisis inicial de documentos contractuales y evidencia tecnica.",
                    "validator_consensus": 0.8,
                },
                {
                    "round": 2,
                    "summary": "Revision profunda de similitud de codigo y timeline de desarrollo.",
                    "validator_consensus": 0.75,
                },
            ],
        },
    }

    # --- Case 3: RESOLVED ---
    case3_id = "case-demo-003"
    case3 = {
        "case_id": case3_id,
        "on_chain_dispute_id": "gl-dispute-0x7a3",
        "claimant_id": user1["user_id"],
        "claimant_address": user1["wallet_address"],
        "claimant_name": user1["display_name"],
        "respondent_address": "0xResp0004aaBBccDDeeFF00112233445566778899",
        "respondent_name": "CloudBridge Payments Ltd.",
        "category": "fraud",
        "title": "Fraude en Procesamiento de Pagos — Cobros No Autorizados",
        "description": (
            "El proveedor de servicios de pago proceso transacciones duplicadas y cobros "
            "no autorizados por un monto total de USD 23,500. A pesar de multiples "
            "reclamos formales, el demandado no ha reembolsado los montos ni ha "
            "proporcionado documentacion de respaldo para las transacciones disputadas."
        ),
        "status": "RESOLVED",
        "escrow_amount": 23500,
        "filing_fee": 350,
        "current_round": 3,
        "appeal_count": 0,
        "created_at": (now - timedelta(days=45)).isoformat(),
        "updated_at": (now - timedelta(days=5)).isoformat(),
        "contract_result": {"dispute_id": "gl-dispute-0x7a3", "tx_hash": "0xghi789..."},
        "verdict": {
            "winner": "claimant",
            "escrow_split": {"claimant_pct": 85, "respondent_pct": 15},
            "claimant_amount": 19975,
            "respondent_amount": 3525,
            "reasoning": (
                "La evidencia presentada demuestra de manera contundente que se realizaron "
                "cobros duplicados sin autorizacion del comerciante. Los registros de la "
                "blockchain confirman las transacciones disputadas. Se ordena la devolucion "
                "del 85%% del monto en custodia al demandante."
            ),
            "rendered_at": (now - timedelta(days=7)).isoformat(),
        },
        "ai_analysis": {
            "strengths_claimant": [
                "Registros de transacciones blockchain verificables mostrando duplicados.",
                "Comunicaciones formales de reclamo con acuse de recibo.",
                "Peritaje contable independiente confirmando discrepancias.",
            ],
            "weaknesses_claimant": [
                "Demora de 30 dias en presentar el reclamo formal.",
            ],
            "strengths_respondent": [
                "El demandado alego fallo tecnico temporal en el sistema de procesamiento.",
            ],
            "weaknesses_respondent": [
                "No presento logs del sistema ni evidencia del supuesto fallo tecnico.",
                "Patron de cobros duplicados afecto a multiples comerciantes.",
                "Incumplimiento de regulaciones de proteccion al consumidor.",
            ],
            "preliminary_assessment": "Caso claramente favorable al demandante (92%% de certeza). La evidencia on-chain es irrefutable y el demandado no logro justificar los cobros.",
            "confidence": 0.92,
            "deliberation_rounds": [
                {"round": 1, "summary": "Verificacion de transacciones on-chain.", "validator_consensus": 0.95},
                {"round": 2, "summary": "Analisis de comunicaciones y reclamos.", "validator_consensus": 0.90},
                {"round": 3, "summary": "Evaluacion final con peritaje contable.", "validator_consensus": 0.92},
            ],
        },
    }

    # --- Case 4: RESOLVED — Maria vs TechCorp (hero demo story) ---
    maria_user = {
        "user_id": "usr-demo-maria-003",
        "email": "maria@veritas.legal",
        "password_hash": hash_password("demo1234"),
        "display_name": "Maria Rodriguez",
        "wallet_address": "0xMaria003aaBBccDDeeFF00112233445566778899",
        "created_at": "2026-01-10T11:00:00+00:00",
    }
    db_put_user(maria_user)

    case4_id = "case-demo-004"
    case4 = {
        "case_id": case4_id,
        "on_chain_dispute_id": "gl-dispute-0x7a4",
        "claimant_id": maria_user["user_id"],
        "claimant_address": maria_user["wallet_address"],
        "claimant_name": "Maria Rodriguez",
        "respondent_address": "0xTechCorp5aaBBccDDeeFF00112233445566778899",
        "respondent_name": "TechCorp GmbH (Berlin)",
        "category": "service_dispute",
        "title": "Maria Rodriguez (Buenos Aires) vs TechCorp GmbH (Berlin) — Unpaid Web Development",
        "description": (
            "Maria Rodriguez, a freelance web developer based in Buenos Aires, was contracted by "
            "TechCorp GmbH (Berlin) to redesign their e-commerce platform for $2,000 USD. The "
            "project scope included responsive redesign, checkout flow optimization, and Stripe "
            "payment integration. Maria delivered all milestones on time and TechCorp's project "
            "manager acknowledged receipt and satisfactory completion via email on February 12, 2026. "
            "Despite the acknowledged delivery, TechCorp has not paid the agreed $2,000. Three "
            "Stripe payment requests were sent and all were declined or ignored. Maria has exhausted "
            "all informal resolution attempts and now seeks arbitration to recover the full amount."
        ),
        "status": "RESOLVED",
        "escrow_amount": 2000,
        "filing_fee": 100,
        "current_round": 3,
        "appeal_count": 0,
        "created_at": (now - timedelta(days=21)).isoformat(),
        "updated_at": (now - timedelta(days=3)).isoformat(),
        "contract_result": {"dispute_id": "gl-dispute-0x7a4", "tx_hash": "0x4a7b8c9d0e1f2a3b..."},
        "verdict": {
            "outcome": "claimant_wins",
            "winner": "claimant",
            "escrow_split": {"claimant_pct": 85, "respondent_pct": 15},
            "claimant_amount": 1700,
            "respondent_amount": 300,
            "confidence": "high",
            "reasoning": (
                "The evidence overwhelmingly supports the claimant's position. The signed freelance "
                "contract (Exhibit A) clearly specifies the deliverables, timeline, and payment terms "
                "of $2,000 USD upon completion. The email correspondence (Exhibit B) contains an "
                "explicit acknowledgment from TechCorp's project manager, Jonas Mueller, dated "
                "February 12, 2026, stating: 'All deliverables received and approved. Great work, "
                "Maria.' This constitutes acceptance of the work product.\n\n"
                "The Stripe payment records (Exhibit C) demonstrate three separate payment attempts "
                "initiated by Maria between February 15-28, all of which were declined on TechCorp's "
                "end. TechCorp did not submit any evidence of defective work, missed deadlines, or "
                "contract breach. Their sole defense — that internal budget reallocation delayed "
                "payment — does not constitute a valid legal defense against a completed contractual "
                "obligation.\n\n"
                "RULING: The AI arbitration panel finds in favor of the claimant, Maria Rodriguez, "
                "with 92% confidence. TechCorp GmbH is ordered to pay 85% of the escrowed amount "
                "($1,700) to the claimant. The remaining 15% ($300) accounts for the platform fee "
                "and is returned to the respondent's escrow balance. This dispute, which would cost "
                "$91,000+ and take 12-18 months in traditional arbitration, was resolved in under "
                "48 hours for less than $1 in transaction fees on GenLayer."
            ),
            "rendered_at": (now - timedelta(days=4)).isoformat(),
        },
        "ai_analysis": {
            "evidence_summary": (
                "Four pieces of evidence were analyzed: a signed freelance contract, email thread "
                "with delivery acknowledgment, Stripe payment attempt records, and the project "
                "deliverable screenshots with timestamps."
            ),
            "strengths_claimant": [
                "Signed contract with clear scope, deliverables, timeline, and payment terms ($2,000 USD).",
                "Email from TechCorp PM (Jonas Mueller) explicitly acknowledging satisfactory delivery: 'All deliverables received and approved.'",
                "Three documented Stripe payment requests (Feb 15, 21, 28) — all declined on respondent's end.",
                "Timestamped screenshots and Git commit history proving on-time delivery of all milestones.",
            ],
            "weaknesses_claimant": [
                "Contract was informal (email-based agreement rather than a notarized document).",
                "No escalation to TechCorp's legal department before filing arbitration.",
            ],
            "strengths_respondent": [
                "TechCorp claimed internal budget reallocation caused the delay (not outright refusal to pay).",
            ],
            "weaknesses_respondent": [
                "No evidence submitted to support the budget reallocation claim.",
                "Delivery was explicitly acknowledged — respondent cannot claim non-performance.",
                "Three payment attempts were ignored without any communication or counter-proposal.",
                "No evidence of defective work, missed deadlines, or scope creep.",
            ],
            "inconsistencies": [
                "TechCorp acknowledged delivery but did not pay — these positions are contradictory.",
                "Respondent's 'budget reallocation' defense was raised only after arbitration was filed.",
            ],
            "preliminary_assessment": "favor_claimant",
            "confidence": 0.92,
            "deliberation_rounds": [
                {
                    "round": 1,
                    "summary": "Initial review of contract terms and delivery evidence. All four milestones verified as complete.",
                    "validator_consensus": 0.95,
                },
                {
                    "round": 2,
                    "summary": "Deep analysis of email correspondence. TechCorp PM's delivery acknowledgment is unambiguous and constitutes acceptance.",
                    "validator_consensus": 0.93,
                },
                {
                    "round": 3,
                    "summary": "Final assessment including payment records analysis. Three declined Stripe payments confirm non-payment despite acknowledged delivery. Verdict: claimant wins.",
                    "validator_consensus": 0.92,
                },
            ],
        },
        "reputation_update": {
            "maria": {"score_before": 500, "score_after": 530, "change": "+30 (won as claimant)"},
            "techcorp": {"score_before": 500, "score_after": 480, "change": "-20 (lost as respondent)"},
        },
    }

    db_put_case(case1)
    db_put_case(case2)
    db_put_case(case3)
    db_put_case(case4)

    # --- Evidence for Case 4 (Maria vs TechCorp) ---
    ev_maria_1 = {
        "evidence_id": "ev-demo-m01",
        "case_id": case4_id,
        "submitter_id": maria_user["user_id"],
        "submitter_address": maria_user["wallet_address"],
        "evidence_type": "document",
        "description": "Signed freelance contract between Maria Rodriguez and TechCorp GmbH — scope, deliverables, $2,000 payment terms",
        "file_name": "Freelance_Contract_Maria_TechCorp.pdf",
        "file_hash": "e1a2b3c4d5e6f7890123456789abcdef01234567890abcdef01234567890abc1",
        "file_size": 312000,
        "content_type": "application/pdf",
        "uploaded_at": (now - timedelta(days=19)).isoformat(),
        "contract_result": {},
    }
    ev_maria_2 = {
        "evidence_id": "ev-demo-m02",
        "case_id": case4_id,
        "submitter_id": maria_user["user_id"],
        "submitter_address": maria_user["wallet_address"],
        "evidence_type": "communication",
        "description": "Email thread with TechCorp PM Jonas Mueller — includes delivery acknowledgment: 'All deliverables received and approved'",
        "file_name": "Email_Thread_TechCorp_Delivery_Ack.pdf",
        "file_hash": "f2b3c4d5e6f7890123456789abcdef01234567890abcdef01234567890abcd2",
        "file_size": 187000,
        "content_type": "application/pdf",
        "uploaded_at": (now - timedelta(days=19)).isoformat(),
        "contract_result": {},
    }
    ev_maria_3 = {
        "evidence_id": "ev-demo-m03",
        "case_id": case4_id,
        "submitter_id": maria_user["user_id"],
        "submitter_address": maria_user["wallet_address"],
        "evidence_type": "transaction",
        "description": "Stripe payment attempt records — 3 invoices sent (Feb 15, 21, 28), all declined on TechCorp's end",
        "file_name": "Stripe_Payment_Attempts.pdf",
        "file_hash": "a3c4d5e6f7890123456789abcdef01234567890abcdef01234567890abcde3",
        "file_size": 95000,
        "content_type": "application/pdf",
        "uploaded_at": (now - timedelta(days=18)).isoformat(),
        "contract_result": {},
    }
    ev_maria_4 = {
        "evidence_id": "ev-demo-m04",
        "case_id": case4_id,
        "submitter_id": maria_user["user_id"],
        "submitter_address": maria_user["wallet_address"],
        "evidence_type": "document",
        "description": "Project deliverable screenshots with timestamps and Git commit history proving on-time completion",
        "file_name": "Deliverable_Screenshots_GitLog.pdf",
        "file_hash": "b4d5e6f7890123456789abcdef01234567890abcdef01234567890abcdef4",
        "file_size": 2450000,
        "content_type": "application/pdf",
        "uploaded_at": (now - timedelta(days=18)).isoformat(),
        "contract_result": {},
    }
    db_put_evidence(ev_maria_1)
    db_put_evidence(ev_maria_2)
    db_put_evidence(ev_maria_3)
    db_put_evidence(ev_maria_4)

    # --- Evidence for Case 2 ---
    ev1 = {
        "evidence_id": "ev-demo-001",
        "case_id": case2_id,
        "submitter_id": user2["user_id"],
        "submitter_address": user2["wallet_address"],
        "evidence_type": "document",
        "description": "Acuerdo de Confidencialidad (NDA) firmado entre ambas partes",
        "file_name": "NDA_Firmado_2025.pdf",
        "file_hash": "a1b2c3d4e5f6789012345678abcdef0123456789abcdef0123456789abcdef01",
        "file_size": 245000,
        "content_type": "application/pdf",
        "uploaded_at": (now - timedelta(days=12)).isoformat(),
        "contract_result": {},
    }
    ev2 = {
        "evidence_id": "ev-demo-002",
        "case_id": case2_id,
        "submitter_id": user2["user_id"],
        "submitter_address": user2["wallet_address"],
        "evidence_type": "expert_report",
        "description": "Analisis de similitud de codigo por perito independiente",
        "file_name": "Peritaje_Codigo_Similitud.pdf",
        "file_hash": "b2c3d4e5f6789012345678abcdef0123456789abcdef0123456789abcdef0102",
        "file_size": 1240000,
        "content_type": "application/pdf",
        "uploaded_at": (now - timedelta(days=10)).isoformat(),
        "contract_result": {},
    }
    ev3 = {
        "evidence_id": "ev-demo-003",
        "case_id": case3_id,
        "submitter_id": user1["user_id"],
        "submitter_address": user1["wallet_address"],
        "evidence_type": "transaction",
        "description": "Registros de transacciones duplicadas en la blockchain",
        "file_name": "TX_Records_Duplicates.csv",
        "file_hash": "c3d4e5f6789012345678abcdef0123456789abcdef0123456789abcdef010203",
        "file_size": 89000,
        "content_type": "text/csv",
        "uploaded_at": (now - timedelta(days=40)).isoformat(),
        "contract_result": {},
    }
    ev4 = {
        "evidence_id": "ev-demo-004",
        "case_id": case3_id,
        "submitter_id": user1["user_id"],
        "submitter_address": user1["wallet_address"],
        "evidence_type": "communication",
        "description": "Correos de reclamo formal con acuse de recibo del demandado",
        "file_name": "Reclamos_Formales.pdf",
        "file_hash": "d4e5f6789012345678abcdef0123456789abcdef0123456789abcdef01020304",
        "file_size": 567000,
        "content_type": "application/pdf",
        "uploaded_at": (now - timedelta(days=38)).isoformat(),
        "contract_result": {},
    }
    db_put_evidence(ev1)
    db_put_evidence(ev2)
    db_put_evidence(ev3)
    db_put_evidence(ev4)

    # --- Timeline events ---
    # Case 1
    add_timeline_event(case1_id, "CASE_FILED", "Caso presentado por Alice Montoya", actor=user1["user_id"])

    # Case 2
    add_timeline_event(case2_id, "CASE_FILED", "Caso presentado por Roberto Vega", actor=user2["user_id"])
    add_timeline_event(case2_id, "EVIDENCE_SUBMITTED", "NDA firmado subido como evidencia", actor=user2["user_id"])
    add_timeline_event(case2_id, "EVIDENCE_SUBMITTED", "Peritaje de codigo subido como evidencia", actor=user2["user_id"])
    add_timeline_event(case2_id, "AI_ANALYSIS", "Analisis de IA completado — Ronda 1", actor="system")
    add_timeline_event(case2_id, "DELIBERATION_ADVANCED", "Deliberacion avanzada a ronda 2", actor="system")
    add_timeline_event(case2_id, "AI_ANALYSIS", "Analisis de IA completado — Ronda 2", actor="system")

    # Case 3
    add_timeline_event(case3_id, "CASE_FILED", "Caso presentado por Alice Montoya", actor=user1["user_id"])
    add_timeline_event(case3_id, "EVIDENCE_SUBMITTED", "Registros de transacciones subidos", actor=user1["user_id"])
    add_timeline_event(case3_id, "EVIDENCE_SUBMITTED", "Correos de reclamo subidos", actor=user1["user_id"])
    add_timeline_event(case3_id, "AI_ANALYSIS", "Analisis de IA completado — Ronda 1", actor="system")
    add_timeline_event(case3_id, "DELIBERATION_ADVANCED", "Deliberacion avanzada a ronda 2", actor="system")
    add_timeline_event(case3_id, "AI_ANALYSIS", "Analisis de IA completado — Ronda 2", actor="system")
    add_timeline_event(case3_id, "DELIBERATION_ADVANCED", "Deliberacion avanzada a ronda 3", actor="system")
    add_timeline_event(case3_id, "VERDICT_RENDERED", "Veredicto final emitido — Demandante gana (85/15)", actor="system")
    add_timeline_event(case3_id, "CASE_RESOLVED", "Caso resuelto — Fondos distribuidos", actor="system")

    # Case 4 (Maria vs TechCorp)
    add_timeline_event(case4_id, "CASE_FILED", "Dispute filed by Maria Rodriguez (Buenos Aires) against TechCorp GmbH (Berlin) — $2,000 unpaid web development", actor=maria_user["user_id"])
    add_timeline_event(case4_id, "EVIDENCE_SUBMITTED", "Freelance contract uploaded (Exhibit A) — scope, deliverables, $2,000 payment terms", actor=maria_user["user_id"])
    add_timeline_event(case4_id, "EVIDENCE_SUBMITTED", "Email correspondence uploaded (Exhibit B) — TechCorp PM acknowledged delivery: 'All deliverables received and approved'", actor=maria_user["user_id"])
    add_timeline_event(case4_id, "EVIDENCE_SUBMITTED", "Stripe payment records uploaded (Exhibit C) — 3 payment attempts declined by TechCorp", actor=maria_user["user_id"])
    add_timeline_event(case4_id, "EVIDENCE_SUBMITTED", "Deliverable screenshots and Git history uploaded (Exhibit D) — proves on-time milestone completion", actor=maria_user["user_id"])
    add_timeline_event(case4_id, "AI_ANALYSIS", "AI analysis round 1 complete — contract terms verified, all 4 milestones confirmed delivered", actor="system")
    add_timeline_event(case4_id, "DELIBERATION_ADVANCED", "Deliberation advanced to round 2 — analyzing email correspondence", actor="system")
    add_timeline_event(case4_id, "AI_ANALYSIS", "AI analysis round 2 complete — delivery acknowledgment from TechCorp PM confirmed as unambiguous acceptance", actor="system")
    add_timeline_event(case4_id, "DELIBERATION_ADVANCED", "Deliberation advanced to round 3 — final payment records review", actor="system")
    add_timeline_event(case4_id, "AI_ANALYSIS", "AI analysis round 3 complete — 3 declined Stripe payments confirm non-payment pattern. Validator consensus: 92%", actor="system")
    add_timeline_event(case4_id, "VERDICT_RENDERED", "VERDICT: Claimant wins (85/15 split). Maria receives $1,700. Confidence: HIGH (92%). Resolved in <48 hours for <$1 vs $91K+ traditional.", actor="system")
    add_timeline_event(case4_id, "ESCROW_DISTRIBUTED", "Escrow distributed: $1,700 to Maria Rodriguez, $300 returned to TechCorp GmbH", actor="system")
    add_timeline_event(case4_id, "REPUTATION_UPDATED", "Reputation updated — Maria: 500 -> 530 (+30, won as claimant). TechCorp: 500 -> 480 (-20, lost as respondent)", actor="system")
    add_timeline_event(case4_id, "CASE_RESOLVED", "Case fully resolved. Cross-border dispute (Argentina/Germany) settled on-chain without lawyers, courts, or jurisdictional complexity.", actor="system")

    logger.info("Demo data seeded successfully: 3 users, 4 cases (incl. Maria vs TechCorp hero story), 8 evidence items")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    seed_demo_data()
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

# ===================================================================
#  DEMO / PUBLIC ENDPOINTS (no auth required for hackathon demo)
# ===================================================================

@app.get("/api/demo/cases", tags=["Demo"])
async def demo_list_cases():
    """List all cases without authentication (demo mode)."""
    all_cases = db_all_cases()
    all_cases.sort(key=lambda x: x["created_at"], reverse=True)
    return {"cases": all_cases, "total": len(all_cases)}


@app.get("/api/demo/cases/{case_id}", tags=["Demo"])
async def demo_get_case(case_id: str):
    """Get full case details without authentication (demo mode)."""
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    evidence = db_get_evidence(case_id)
    timeline = db_get_timeline(case_id)
    return {
        **case,
        "evidence": evidence,
        "evidence_count": len(evidence),
        "timeline": timeline,
        "timeline_count": len(timeline),
    }


@app.get("/api/demo/cases/{case_id}/evidence", tags=["Demo"])
async def demo_list_evidence(case_id: str):
    """List evidence without auth (demo mode)."""
    evidence = db_get_evidence(case_id)
    return {"case_id": case_id, "evidence": evidence, "total": len(evidence)}


@app.get("/api/demo/cases/{case_id}/timeline", tags=["Demo"])
async def demo_get_timeline(case_id: str):
    """Get timeline without auth (demo mode)."""
    events = db_get_timeline(case_id)
    return {"case_id": case_id, "events": events, "total": len(events)}


@app.get("/api/demo/analytics", tags=["Demo"])
async def demo_analytics():
    """Platform analytics without auth (demo mode)."""
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

    return {
        "total_cases": total,
        "cases_by_status": by_status,
        "cases_by_category": by_category,
        "total_escrow_value": total_escrow,
        "resolution_rate_pct": round(resolution_rate, 2),
        "resolved_count": len(resolved_cases),
        "active_count": total - len(resolved_cases),
    }


@app.get("/api/demo/users", tags=["Demo"])
async def demo_users():
    """List demo users (no passwords) for demo mode."""
    users = db_all_users()
    return {
        "users": [
            {
                "user_id": u["user_id"],
                "email": u["email"],
                "display_name": u["display_name"],
                "wallet_address": u["wallet_address"],
                "created_at": u["created_at"],
            }
            for u in users
        ]
    }


@app.get("/api/demo/reputation/{wallet_address}", tags=["Demo"])
async def demo_reputation(wallet_address: str):
    """Get reputation for demo mode with realistic data."""
    # Return pre-computed demo reputation
    demo_reputations = {
        "0xAlice0001aaBBccDDeeFF00112233445566778899": {
            "address": "0xAlice0001aaBBccDDeeFF00112233445566778899",
            "display_name": "Alice Montoya",
            "score": 1847,
            "cases_filed": 2,
            "cases_responded": 1,
            "cases_won": 1,
            "cases_lost": 0,
            "cases_active": 2,
            "compliance_score": 95,
            "total_value_recovered": 19975,
            "win_rate": 100,
        },
        "0xBob00002aaBBccDDeeFF00112233445566778899": {
            "address": "0xBob00002aaBBccDDeeFF00112233445566778899",
            "display_name": "Roberto Vega",
            "score": 1623,
            "cases_filed": 1,
            "cases_responded": 0,
            "cases_won": 0,
            "cases_lost": 0,
            "cases_active": 1,
            "compliance_score": 88,
            "total_value_recovered": 0,
            "win_rate": 0,
        },
        "0xMaria003aaBBccDDeeFF00112233445566778899": {
            "address": "0xMaria003aaBBccDDeeFF00112233445566778899",
            "display_name": "Maria Rodriguez",
            "score": 530,
            "cases_filed": 1,
            "cases_responded": 0,
            "cases_won": 1,
            "cases_lost": 0,
            "cases_active": 0,
            "compliance_score": 100,
            "total_value_recovered": 1700,
            "win_rate": 100,
        },
        "0xTechCorp5aaBBccDDeeFF00112233445566778899": {
            "address": "0xTechCorp5aaBBccDDeeFF00112233445566778899",
            "display_name": "TechCorp GmbH",
            "score": 480,
            "cases_filed": 0,
            "cases_responded": 1,
            "cases_won": 0,
            "cases_lost": 1,
            "cases_active": 0,
            "compliance_score": 80,
            "total_value_recovered": 0,
            "win_rate": 0,
        },
    }
    rep = demo_reputations.get(wallet_address)
    if rep:
        return rep
    return {
        "address": wallet_address,
        "score": 500,
        "cases_filed": 0,
        "cases_responded": 0,
        "cases_won": 0,
        "cases_lost": 0,
        "compliance_score": 100,
    }


@app.post("/api/demo/cases", tags=["Demo"], status_code=201)
async def demo_create_case(body: CaseCreate):
    """Create a case without authentication (demo mode)."""
    case_id = str(uuid.uuid4())
    case = {
        "case_id": case_id,
        "on_chain_dispute_id": f"gl-dispute-{case_id[:8]}",
        "claimant_id": "usr-demo-alice-001",
        "claimant_address": "0xAlice0001aaBBccDDeeFF00112233445566778899",
        "claimant_name": "Alice Montoya",
        "respondent_address": body.respondent_address,
        "respondent_name": "Parte Demandada",
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
        "contract_result": {"dispute_id": f"gl-dispute-{case_id[:8]}", "tx_hash": f"0x{case_id[:16]}..."},
    }
    db_put_case(case)
    add_timeline_event(case_id, "CASE_FILED", "Caso presentado (modo demo)", actor="usr-demo-alice-001")
    return case


@app.post("/api/demo/cases/{case_id}/analyze", tags=["Demo"])
async def demo_analyze(case_id: str):
    """
    Trigger mock AI analysis without GenLayer RPC (demo mode).

    Returns realistic AI analysis results with strengths, weaknesses,
    confidence scores, and validator consensus data.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case.get("ai_analysis"):
        return {
            "case_id": case_id,
            "status": "analysis_complete",
            "round": case.get("current_round", 1),
            "analysis": case["ai_analysis"],
            "message": "AI analysis already completed for this case.",
        }

    # Generate realistic mock analysis based on case data
    analysis = {
        "evidence_summary": f"Analyzed {len(db_get_evidence(case_id))} evidence items for case '{case['title']}'.",
        "strengths_claimant": [
            "Documentary evidence supports the claimant's core assertions.",
            "Timeline of events is consistent and well-documented.",
            "Communication records show good-faith attempts at resolution.",
        ],
        "weaknesses_claimant": [
            "Some claims lack independent corroboration.",
        ],
        "strengths_respondent": [
            "Respondent raised procedural objections that merit consideration.",
        ],
        "weaknesses_respondent": [
            "No substantive evidence submitted to counter the claimant's primary claim.",
            "Failed to respond to multiple resolution attempts.",
        ],
        "inconsistencies": [
            "Respondent's stated position is inconsistent with their documented actions.",
        ],
        "preliminary_assessment": "favor_claimant",
        "confidence": 0.78,
        "deliberation_rounds": [
            {
                "round": 1,
                "summary": "Initial evidence review and document verification.",
                "validator_consensus": 0.82,
            },
        ],
    }

    case["ai_analysis"] = analysis
    case["status"] = "DELIBERATION"
    case["updated_at"] = datetime.now(timezone.utc).isoformat()
    db_put_case(case)

    add_timeline_event(
        case_id, "AI_ANALYSIS",
        f"AI evidence analysis completed (demo mode) — preliminary: {analysis['preliminary_assessment']}, confidence: {analysis['confidence']}",
        actor="system",
    )

    return {
        "case_id": case_id,
        "status": "analysis_complete",
        "round": case.get("current_round", 1),
        "analysis": analysis,
        "validator_consensus": 0.82,
        "message": "AI analysis completed via GenLayer equivalence principle (demo mode).",
    }


@app.post("/api/demo/cases/{case_id}/verdict", tags=["Demo"])
async def demo_verdict(case_id: str):
    """
    Render a mock AI verdict without GenLayer RPC (demo mode).

    Returns a realistic verdict with outcome, escrow split, confidence,
    and detailed multi-paragraph reasoning.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case.get("verdict"):
        return {
            "case_id": case_id,
            "status": "VERDICT",
            "verdict": case["verdict"],
            "message": "Verdict already rendered for this case.",
        }

    escrow = case.get("escrow_amount", 0)
    claimant_pct = 85
    claimant_amount = (escrow * claimant_pct) // 100
    respondent_amount = escrow - claimant_amount

    verdict = {
        "outcome": "claimant_wins",
        "winner": "claimant",
        "escrow_split": {"claimant_pct": claimant_pct, "respondent_pct": 100 - claimant_pct},
        "claimant_amount": claimant_amount,
        "respondent_amount": respondent_amount,
        "confidence": "high",
        "reasoning": (
            f"Based on thorough analysis of all submitted evidence, the AI arbitration panel "
            f"finds in favor of the claimant. The documentary evidence establishes a clear "
            f"contractual obligation that was not fulfilled by the respondent. The claimant "
            f"demonstrated good-faith performance and exhausted informal resolution channels "
            f"before seeking arbitration.\n\n"
            f"The respondent failed to provide substantive evidence to counter the primary claim. "
            f"The communication records confirm that the respondent acknowledged the obligation "
            f"but did not fulfill it. No valid legal defense was presented.\n\n"
            f"RULING: {claimant_pct}% of the escrowed amount (${claimant_amount:,}) is awarded "
            f"to the claimant. The remaining {100 - claimant_pct}% (${respondent_amount:,}) is "
            f"returned to the respondent. This verdict was reached with HIGH confidence "
            f"and 92% validator consensus across the GenLayer network."
        ),
        "rendered_at": datetime.now(timezone.utc).isoformat(),
    }

    case["verdict"] = verdict
    case["status"] = "VERDICT"
    case["updated_at"] = datetime.now(timezone.utc).isoformat()
    db_put_case(case)

    add_timeline_event(
        case_id, "VERDICT_RENDERED",
        f"Verdict rendered: claimant wins ({claimant_pct}/{100 - claimant_pct} split). "
        f"Claimant receives ${claimant_amount:,}. Confidence: HIGH.",
        actor="system",
        metadata=verdict,
    )

    return {
        "case_id": case_id,
        "status": "VERDICT",
        "verdict": verdict,
        "message": "Binding verdict rendered via GenLayer AI consensus (demo mode).",
    }


@app.post("/api/demo/cases/{case_id}/resolve", tags=["Demo"])
async def demo_resolve(case_id: str):
    """
    Resolve a case and distribute escrow without GenLayer RPC (demo mode).

    Distributes escrowed funds per the verdict split and updates reputations.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case["status"] == "RESOLVED":
        return {
            "case_id": case_id,
            "status": "RESOLVED",
            "message": "Case already resolved.",
            "verdict": case.get("verdict"),
        }

    if not case.get("verdict"):
        raise HTTPException(status_code=400, detail="No verdict rendered yet. Call /verdict first.")

    verdict = case["verdict"]
    escrow = case.get("escrow_amount", 0)
    claimant_pct = verdict.get("escrow_split", {}).get("claimant_pct", 85)
    claimant_amount = (escrow * claimant_pct) // 100
    respondent_amount = escrow - claimant_amount

    case["status"] = "RESOLVED"
    case["updated_at"] = datetime.now(timezone.utc).isoformat()
    db_put_case(case)

    add_timeline_event(
        case_id, "ESCROW_DISTRIBUTED",
        f"Escrow distributed: ${claimant_amount:,} to claimant, ${respondent_amount:,} to respondent",
        actor="system",
    )
    add_timeline_event(
        case_id, "REPUTATION_UPDATED",
        "Reputation scores updated — claimant: +30 (won), respondent: -20 (lost)",
        actor="system",
    )
    add_timeline_event(
        case_id, "CASE_RESOLVED",
        "Case fully resolved. Funds distributed per AI verdict.",
        actor="system",
    )

    return {
        "case_id": case_id,
        "status": "RESOLVED",
        "escrow_total": escrow,
        "claimant_receives": claimant_amount,
        "respondent_receives": respondent_amount,
        "claimant_pct": claimant_pct,
        "reputation_changes": {
            "claimant": "+30 (won as claimant)",
            "respondent": "-20 (lost as respondent)",
        },
        "message": "Case resolved. Escrow distributed and reputations updated.",
        "cost_comparison": {
            "traditional_arbitration_cost": "$91,000+",
            "traditional_arbitration_time": "12-18 months",
            "veritas_cost": "<$1 (GenLayer transaction fees)",
            "veritas_time": "Minutes to hours",
            "savings": "99.999%",
        },
    }


@app.post("/api/demo/cases/{case_id}/full-flow", tags=["Demo"])
async def demo_full_flow(case_id: str):
    """
    Run the complete arbitration flow in one call (demo mode).

    Executes: analyze -> verdict -> resolve in sequence, returning
    the full lifecycle result. Useful for demonstrating the end-to-end
    flow during presentations.
    """
    case = db_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    results = {"case_id": case_id, "steps": []}

    # Step 1: Analyze (if not already done)
    if not case.get("ai_analysis"):
        analysis_result = await demo_analyze(case_id)
        results["steps"].append({"step": "analyze", "result": analysis_result})
        case = db_get_case(case_id)  # Reload
    else:
        results["steps"].append({"step": "analyze", "result": "Already completed"})

    # Step 2: Verdict (if not already done)
    if not case.get("verdict"):
        verdict_result = await demo_verdict(case_id)
        results["steps"].append({"step": "verdict", "result": verdict_result})
        case = db_get_case(case_id)  # Reload
    else:
        results["steps"].append({"step": "verdict", "result": "Already rendered"})

    # Step 3: Resolve (if not already done)
    if case["status"] != "RESOLVED":
        resolve_result = await demo_resolve(case_id)
        results["steps"].append({"step": "resolve", "result": resolve_result})
    else:
        results["steps"].append({"step": "resolve", "result": "Already resolved"})

    # Final state
    final_case = db_get_case(case_id)
    results["final_state"] = final_case
    results["message"] = "Full arbitration lifecycle completed."

    return results


@app.get("/api/demo/all-evidence", tags=["Demo"])
async def demo_all_evidence():
    """List all evidence across all cases (demo mode)."""
    all_ev = db_all_evidence()
    flat = []
    for case_id, evs in all_ev.items():
        for e in evs:
            flat.append(e)
    flat.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return {"evidence": flat, "total": len(flat)}


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
