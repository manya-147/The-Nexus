# model.py

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String

from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(Base):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)

    full_name = Column(String)

    email = Column(String, unique=True)

    phone = Column(String)

    dob = Column(String)

    password = Column(String)

    plan = Column(String, default="FREE")

    plan_started = Column(String, nullable=True)

class Payment(Base):

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer)

    plan = Column(String)

    amount = Column(Integer)

    method = Column(String)

    status = Column(String, default="SUCCESS")

    reference = Column(String, unique=True)

    upi_id = Column(String, nullable=True)

    card_last4 = Column(String, nullable=True)

    card_holder = Column(String, nullable=True)

    created_at = Column(String)


class Agent(Base):

    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer)

    name = Column(String)

    role = Column(String)

    type = Column(String)

    description = Column(String)

    status = Column(String, default="Active")

    icon = Column(String, default="🤖")

    created_at = Column(String)


from pydantic import BaseModel
from typing import Optional


class AgentRequest(BaseModel):
    name: str
    role: str
    type: str
    description: Optional[str] = ""
    status: Optional[str] = "Active"
    icon: Optional[str] = "🤖"


class SignupRequest(BaseModel):
    full_name: str
    email: str
    phone: str
    dob: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class PaymentRequest(BaseModel):
    plan: str
    amount: int
    method: str                      # COD | UPI | CARD
    upi_id: Optional[str] = None
    scanned: Optional[bool] = False  # True when paid via the UPI QR scanner
    card_number: Optional[str] = None
    card_holder: Optional[str] = None
    expiry: Optional[str] = None
    pin: Optional[str] = None


class ChatMessage(Base):

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer)

    agent = Column(String)      # research | coding | marketing | support

    role = Column(String)       # user | ai

    content = Column(String)

    created_at = Column(String)


class ChatRequest(BaseModel):
    agent: str
    message: str