# Copyright (c) 2026, Sermed Turizm
# Idempotent migration for participant status and manual cost semantics.

from __future__ import annotations

import frappe


PAYING_STATUS = "UMRECI"
STATUSES = {
    "UMRECI",
    "HOCA",
    "HOCA_ESI",
    "HOCA_COCUGU",
    "FREE",
    "SIRKET_MUDURU",
    "SIRKET_MUDURU_ESI",
    "SIRKET_MUDURU_COCUGU",
}


def _db_name() -> str | None:
    return frappe.local.conf.get("db_name") or getattr(frappe.db, "cur_db_name", None)


def _has_table(tablename: str) -> bool:
    return bool(frappe.db.sql("SHOW TABLES LIKE %s", (tablename,)))


def _col_exists(db: str | None, table: str, column: str) -> bool:
    if not db:
        return False
    result = frappe.db.sql(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND BINARY TABLE_NAME = BINARY %s
          AND BINARY COLUMN_NAME = BINARY %s
        """,
        (db, table, column),
    )
    return bool(result and result[0][0])


def _ensure_column(db: str | None, table: str, column: str, ddl: str) -> None:
    if not _col_exists(db, table, column):
        frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD COLUMN {ddl}")


def execute() -> None:
    table = "tabUmre Booking"
    if not _has_table(table):
        return

    db = _db_name()
    _ensure_column(db, table, "statu", "`statu` varchar(140) DEFAULT 'UMRECI'")
    _ensure_column(db, table, "manual_cost", "`manual_cost` decimal(21,9) DEFAULT NULL")
    # Frappe may create Currency columns as NOT NULL during model sync. This field
    # must be nullable so paying customer bookings can explicitly carry no manual override.
    frappe.db.sql_ddl(f"ALTER TABLE `{table}` MODIFY COLUMN `manual_cost` decimal(21,9) NULL DEFAULT NULL")

    valid = tuple(sorted(STATUSES))
    frappe.db.sql(
        f"""
        UPDATE `{table}`
        SET `statu` = %s
        WHERE `statu` IS NULL OR `statu` = '' OR `statu` NOT IN %s
        """,
        (PAYING_STATUS, valid),
    )

    # Non-paying participants are cost-only. Preserve any existing manual_cost and
    # otherwise move the old booking price into manual_cost before zeroing revenue.
    frappe.db.sql(
        f"""
        UPDATE `{table}`
        SET
            `manual_cost` = CASE
                WHEN IFNULL(`manual_cost`, 0) = 0 THEN IFNULL(`ucret`, 0)
                ELSE `manual_cost`
            END,
            `ucret` = 0,
            `diyanet_maliyeti` = 0,
            `toplam_maliyet` = CASE
                WHEN IFNULL(`manual_cost`, 0) = 0 THEN IFNULL(`ucret`, 0)
                ELSE `manual_cost`
            END,
            `kar` = 0 - CASE
                WHEN IFNULL(`manual_cost`, 0) = 0 THEN IFNULL(`ucret`, 0)
                ELSE `manual_cost`
            END - IFNULL(`kms`, 0)
        WHERE `statu` != %s
        """,
        (PAYING_STATUS,),
    )

    # Paying customers must not carry manual override cost.
    frappe.db.sql(
        f"""
        UPDATE `{table}`
        SET `manual_cost` = NULL
        WHERE `statu` = %s
        """,
        (PAYING_STATUS,),
    )
