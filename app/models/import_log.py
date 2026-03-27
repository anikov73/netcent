from datetime import datetime

from sqlalchemy import Integer, String, Text, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class ImportLog(Base):
    __tablename__ = "import_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    total_rows: Mapped[int | None] = mapped_column(Integer)
    new_rows: Mapped[int | None] = mapped_column(Integer)
    duplicate_rows: Mapped[int | None] = mapped_column(Integer)
    error_rows: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)

    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="import_log")
