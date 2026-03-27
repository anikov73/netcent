from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Integer, String, Text, Boolean, Date, TIMESTAMP, DECIMAL, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    description_clean: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="MKD")
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id", ondelete="SET NULL"))
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"))
    is_manually_categorized: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    merchant: Mapped[str | None] = mapped_column(String(255))
    import_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    import_log_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("import_logs.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    category: Mapped["Category | None"] = relationship("Category", back_populates="transactions")
    account: Mapped["Account | None"] = relationship("Account", back_populates="transactions")
    import_log: Mapped["ImportLog | None"] = relationship("ImportLog", back_populates="transactions")
