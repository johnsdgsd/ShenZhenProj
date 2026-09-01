"""到货排程业务层使用的数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class PreparedArrivalData:
    demands: list[dict[str, Any]]
    qualified_stock: list[dict[str, Any]]
    unqualified_stock: list[dict[str, Any]]
    contracts: list[dict[str, Any]]
    supply_notices: list[dict[str, Any]]
    suppliers: list[dict[str, Any]]
    warehouse_areas: list[dict[str, Any]]
    workdays: list[date]


@dataclass
class ArrivalResult:
    schedule_rows: list[dict[str, Any]] = field(default_factory=list)
    capacity_alarm_rows: list[dict[str, Any]] = field(default_factory=list)
    contract_allocation_rows: list[dict[str, Any]] = field(default_factory=list)
    contract_shortage_rows: list[dict[str, Any]] = field(default_factory=list)
    net_demand_rows: list[dict[str, Any]] = field(default_factory=list)
    daily_batch_alert_rows: list[dict[str, Any]] = field(default_factory=list)
    excluded_notice_rows: list[dict[str, Any]] = field(default_factory=list)
