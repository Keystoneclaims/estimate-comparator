from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass

class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True)
    claim_name = Column(String(255), nullable=False)
    insured_name = Column(String(255), nullable=True)
    carrier = Column(String(255), nullable=True)
    claim_number = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    estimates = relationship("Estimate", back_populates="claim")

class Estimate(Base):
    __tablename__ = "estimates"

    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    source = Column(String(50), nullable=False)  # carrier or company
    file_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="estimates")
    lines = relationship("EstimateLineItem", back_populates="estimate")

class EstimateLineItem(Base):
    __tablename__ = "estimate_line_items"

    id = Column(Integer, primary_key=True)
    estimate_id = Column(Integer, ForeignKey("estimates.id"), nullable=False)
    room = Column(String(255), default="")
    category = Column(String(255), default="")
    description = Column(Text, nullable=False)
    quantity = Column(Float, default=0)
    unit = Column(String(50), default="")
    unit_price = Column(Float, default=0)
    total = Column(Float, default=0)
    raw = Column(JSON, default={})

    estimate = relationship("Estimate", back_populates="lines")
