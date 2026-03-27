from datetime import date
from decimal import Decimal

from sqlalchemy import Integer, String, Text, Boolean, Date, DECIMAL, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(255))
    expected_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="MKD")
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)  # monthly, quarterly, yearly, weekly
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[date | None] = mapped_column(Date)
    next_expected: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    category: Mapped["Category | None"] = relationship("Category", back_populates="subscriptions")
