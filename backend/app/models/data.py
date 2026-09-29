from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.system import User


class TimestampMixin:
    """created_at / updated_at 两个字段太常见，抽出来谁要谁继承。

    server_default 让数据库自己填（不靠 Python 传），onupdate 则在每次 UPDATE 时自动刷新。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        # data_source + source_record_id 一起做唯一键：
        # 同一个来源 ID 在两种数据源下可以各存一份，互不冲突
        UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_assets_data_source_source_record_id",
        ),
        Index("ix_assets_asset_type", "asset_type"),
        Index("ix_assets_status", "status"),
        Index("ix_assets_location", "location"),
        Index("ix_assets_category", "category"),
        Index("ix_assets_commissioned_on", "commissioned_on"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # 双数据源隔离：REAL_PUBLIC 是官方导入的历史数据（只读），
    # 以后平台自己新加的走 SYNTHETIC_PLATFORM
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="REAL_PUBLIC")
    asset_type: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    asset_class: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(150))
    location: Mapped[str | None] = mapped_column(String(255))
    parent_source_record_id: Mapped[str | None] = mapped_column(String(100))
    manufacturer: Mapped[str | None] = mapped_column(String(255))
    mrc_code: Mapped[str | None] = mapped_column(String(100))
    serial_number: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    record_code: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(100))
    commissioned_on: Mapped[date | None] = mapped_column(Date)
    withdrawn_on: Mapped[date | None] = mapped_column(Date)
    record_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    source_update_count: Mapped[int | None] = mapped_column(Integer)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    gis_object_id: Mapped[str | None] = mapped_column(String(100))
    gis_layer: Mapped[str | None] = mapped_column(String(100))
    x_location: Mapped[Decimal | None] = mapped_column(Numeric(18, 7))
    y_location: Mapped[Decimal | None] = mapped_column(Numeric(18, 7))


class WorkOrder(TimestampMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_work_orders_data_source_source_record_id",
        ),
        Index("ix_work_orders_asset_id", "asset_id"),
        Index("ix_work_orders_status", "status"),
        Index("ix_work_orders_request_date", "request_date"),
        Index("ix_work_orders_completion_date", "completion_date"),
        Index("ix_work_orders_work_type", "work_type"),
        Index("ix_work_orders_asset_source_record_id", "asset_source_record_id"),
        Index("ix_work_orders_priority", "priority"),
        Index("ix_work_orders_assigned_to_id", "assigned_to_id"),
        Index("ix_work_orders_sla_deadline", "sla_deadline"),
        Index("ix_work_orders_source_record_id", "source_record_id"),
        # 列表页那个关键词搜索就走这个全文索引，不然 220 万行 LIKE 会慢到没法用
        Index(
            "ix_work_orders_search",
            "description",
            "assigned_title",
            mysql_prefix="FULLTEXT",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="REAL_PUBLIC")
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("assets.id", ondelete="SET NULL"),
    )
    asset_source_record_id: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    work_type: Mapped[str | None] = mapped_column(String(150))
    work_class: Mapped[str | None] = mapped_column(String(150))
    request_date: Mapped[date | None] = mapped_column(Date)
    created_source_at: Mapped[datetime | None] = mapped_column(DateTime)
    completion_date: Mapped[date | None] = mapped_column(Date)
    scheduled_end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # 这个 status 是谁写的：DERIVED_FROM_SOURCE = 从来源数据推导出来的（不是人改的）
    # 只有平台自己流转的状态才不是这个值
    status_origin: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="DERIVED_FROM_SOURCE",
    )
    source_status: Mapped[str | None] = mapped_column(String(100))
    source_priority: Mapped[str | None] = mapped_column(String(50))
    assigned_title: Mapped[str | None] = mapped_column(String(150))
    source_notes: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(String(100))
    target: Mapped[str | None] = mapped_column(String(150))
    duration: Mapped[str | None] = mapped_column(String(100))
    job_type: Mapped[str | None] = mapped_column(String(150))
    parent_source_record_id: Mapped[str | None] = mapped_column(String(100))
    is_ppm: Mapped[bool | None] = mapped_column(Boolean)
    is_safety: Mapped[bool | None] = mapped_column(Boolean)
    is_reopened: Mapped[bool | None] = mapped_column(Boolean)
    has_warranty: Mapped[bool | None] = mapped_column(Boolean)
    source_update_count: Mapped[int | None] = mapped_column(Integer)
    source_updated_raw: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[str | None] = mapped_column(String(2))
    sla_policy: Mapped[str | None] = mapped_column(String(20))
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime)
    sla_source: Mapped[str | None] = mapped_column(String(32))
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    assigned_to_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    # 下面两个 relationship 都指向 users，必须用 foreign_keys 明确说是哪一列，
    # 不然 SQLAlchemy 不知道 created_by_id 和 assigned_to_id 各对应哪个。
    #
    # 这两个原来写的是 lazy="joined"（一查工单就自动 JOIN 出对应用户），
    # 2026-09-29 做第 17 步列表接口时去掉了。原因是量出来一个 16 秒的查询：
    #
    #   select(WorkOrder) WHERE id > 1678636 ORDER BY id LIMIT 21
    #     原样跑               -> 16614 ms
    #     EXPLAIN: work_orders  type=range  key=PRIMARY  rows=1079352
    #              Extra=Using temporary; Using filesort
    #              users_1     type=ALL    rows=7  Using join buffer (hash join)
    #     把 JOIN 去掉                    -> 2.5 ms
    #     带 JOIN + FORCE INDEX (PRIMARY)  -> 3.7 ms
    #     同样走 ORM、改成按需加载          -> 4.6 ms
    #
    # 说白了就是：这条 LEFT JOIN 让 MySQL 挑了 hash join，于是它没法再用主键顺序
    # 直接往下拿 21 行，只能把 107 万行先查出来排一遍（filesort）再 limit。
    # LIMIT 21 本来能省的那一大堆活，全白省了。
    #
    # 而且这 JOIN 在这张表上永远是白搭：created_by_id 和 assigned_to_id
    # 实测 222 万行 100% 是 NULL —— 那是平台自己录工单时才会填的字段，
    # 现在库里全是官方导进来的老数据。
    #
    # 去掉之后就是默认的按需加载：真要读 wo.assigned_to 的那一刻才多查一条。
    # 第 18 步做分派会用到它，到时候按需查一次就够了，
    # 不该让每个列表查询都替它买单。
    created_by: Mapped["User | None"] = relationship(
        foreign_keys=[created_by_id],
    )
    assigned_to: Mapped["User | None"] = relationship(
        foreign_keys=[assigned_to_id],
    )
    status_history: Mapped[list["WorkOrderStatusHistory"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan",
    )
    processing_records: Mapped[list["WorkOrderProcessingRecord"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan",
    )


class WorkOrderStatusHistory(Base):
    """工单状态流转的流水账：每改一次状态就落一行，用来说清'这单怎么走过来的'。"""

    __tablename__ = "work_order_status_history"
    __table_args__ = (
        Index("ix_work_order_status_history_work_order_id", "work_order_id"),
        Index("ix_work_order_status_history_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    work_order: Mapped[WorkOrder] = relationship(back_populates="status_history")
    operator: Mapped["User | None"] = relationship(lazy="joined")


class WorkOrderProcessingRecord(Base):
    """处理记录：人在工单下面留的备注/过程说明。"""

    __tablename__ = "work_order_processing_records"
    __table_args__ = (
        Index("ix_work_order_processing_records_work_order_id", "work_order_id"),
        Index("ix_work_order_processing_records_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    work_order: Mapped[WorkOrder] = relationship(back_populates="processing_records")
    user: Mapped["User | None"] = relationship(lazy="joined")


class WorkOrderLabor(TimestampMixin, Base):
    __tablename__ = "work_order_labor"
    __table_args__ = (
        UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_work_order_labor_data_source_source_record_id",
        ),
        Index("ix_work_order_labor_work_order_id", "work_order_id"),
        Index("ix_work_order_labor_work_date", "work_date"),
        Index("ix_work_order_labor_trade", "trade"),
        Index(
            "ix_work_order_labor_source_work_order_record_id",
            "source_work_order_record_id",
        ),
        Index("ix_work_order_labor_source_record_id", "source_record_id"),
        Index(
            "ix_work_order_labor_search",
            "action",
            "description",
            mysql_prefix="FULLTEXT",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="REAL_PUBLIC")
    work_order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("work_orders.id", ondelete="SET NULL"),
    )
    source_work_order_record_id: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str | None] = mapped_column(String(255))
    work_date: Mapped[date | None] = mapped_column(Date)
    trade: Mapped[str | None] = mapped_column(String(150))
    operation_type: Mapped[str | None] = mapped_column(String(100))
    on_text: Mapped[str | None] = mapped_column(String(100))
    off_text: Mapped[str | None] = mapped_column(String(100))
    # 工时和钱都用 Decimal，绝不能用 float（浮点算钱会掉精度）
    hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    entered_at: Mapped[datetime | None] = mapped_column(DateTime)
    correction_flag: Mapped[bool | None] = mapped_column(Boolean)
    job_category: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    misc: Mapped[str | None] = mapped_column(Text)


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_transactions_data_source_source_record_id",
        ),
        Index("ix_transactions_work_order_id", "work_order_id"),
        Index("ix_transactions_status", "status"),
        Index("ix_transactions_transaction_date", "transaction_date"),
        # 出库/入库是按 (来源, 去向) 一起查的，所以做成联合索引
        Index("ix_transactions_to_entity_code", "to_entity", "to_code"),
        Index(
            "ix_transactions_source_work_order_record_id",
            "source_work_order_record_id",
        ),
        Index("ix_transactions_source_record_id", "source_record_id"),
        Index("ix_transactions_request_number", "request_number"),
        Index(
            "ix_transactions_search",
            "description",
            mysql_prefix="FULLTEXT",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="REAL_PUBLIC")
    work_order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("work_orders.id", ondelete="SET NULL"),
    )
    source_work_order_record_id: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    transaction_type: Mapped[str | None] = mapped_column(String(100))
    transaction_date: Mapped[date | None] = mapped_column(Date)
    request_number: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(100))
    from_entity: Mapped[str | None] = mapped_column(String(100))
    from_code: Mapped[str | None] = mapped_column(String(150))
    to_entity: Mapped[str | None] = mapped_column(String(100))
    to_code: Mapped[str | None] = mapped_column(String(150))
    source_update_count: Mapped[int | None] = mapped_column(Integer)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class TransactionDetail(TimestampMixin, Base):
    """交易明细（领了哪些物料、几个、单价多少）。一张交易单对应多行明细。"""

    __tablename__ = "transaction_details"
    __table_args__ = (
        UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_transaction_details_data_source_source_record_id",
        ),
        Index("ix_transaction_details_transaction_id", "transaction_id"),
        Index("ix_transaction_details_part_code", "part_code"),
        Index(
            "ix_transaction_details_transaction_source_record_id",
            "transaction_source_record_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_record_id: Mapped[str] = mapped_column(String(150), nullable=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="REAL_PUBLIC")
    transaction_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("transactions.id", ondelete="SET NULL"),
    )
    transaction_source_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    line_number: Mapped[str | None] = mapped_column(String(100))
    detail_type: Mapped[str | None] = mapped_column(String(100))
    transaction_date: Mapped[date | None] = mapped_column(Date)
    event_source_record_id: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str | None] = mapped_column(String(100))
    part_code: Mapped[str | None] = mapped_column(String(150))
    part_description: Mapped[str | None] = mapped_column(Text)
    part_class: Mapped[str | None] = mapped_column(String(100))
    part_uom: Mapped[str | None] = mapped_column(String(50))
    requested_line: Mapped[str | None] = mapped_column(String(100))
    bin_location: Mapped[str | None] = mapped_column(String(100))
    store_code: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    average_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    request_number: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    attachment: Mapped[str | None] = mapped_column(String(255))
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_last_status_update: Mapped[str | None] = mapped_column(String(255))
    source_sql_identity: Mapped[str | None] = mapped_column(String(100))
