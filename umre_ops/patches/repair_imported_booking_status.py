# Copyright (c) 2026, Sermed Turizm
# Repair imported booking status/manual cost values from the source Excel import.

from __future__ import annotations

import frappe


PAYING_STATUS = "UMRECI"
# Source Excel rows where STATÜ is not UMRECI. Keyed by Umreci.tc_kimlik.
SOURCE_NON_UMRECI = {
    "10205468208": {"statu": "HOCA", "manual_cost": 1223.0},
    "29726548610": {"statu": "HOCA_ESI", "manual_cost": 1223.0},
    "40240144324": {"statu": "HOCA_COCUGU", "manual_cost": 700.0},
    "66016043950": {"statu": "FREE", "manual_cost": 1080.0},
}


def _has_table(tablename: str) -> bool:
    return bool(frappe.db.sql("SHOW TABLES LIKE %s", (tablename,)))


def _log(message: str, data: dict | None = None) -> None:
    frappe.logger("umre_ops.repair_imported_booking_status").info("%s %s", message, data or {})


def execute() -> None:
    if not (_has_table("tabUmre Booking") and _has_table("tabUmreci")):
        return

    repaired_non_umreci = 0
    for tc, source in SOURCE_NON_UMRECI.items():
        bookings = frappe.db.sql(
            """
            SELECT b.name, b.ucret, b.toplam_maliyet, b.manual_cost, b.kms
            FROM `tabUmre Booking` b
            INNER JOIN `tabUmreci` u ON u.name = b.umreci
            WHERE u.tc_kimlik = %s
            """,
            (tc,),
            as_dict=True,
        )
        for booking in bookings:
            manual_cost = source["manual_cost"] or booking.manual_cost or booking.toplam_maliyet or booking.ucret or 0
            frappe.db.set_value(
                "Umre Booking",
                booking.name,
                {
                    "statu": source["statu"],
                    "ucret": 0,
                    "manual_cost": manual_cost,
                    "otel_maliyeti": 0,
                    "ucak_maliyeti": 0,
                    "vize_maliyeti": 0,
                    "diyanet_maliyeti": 0,
                    "diyanet_kart_var": 0,
                    "toplam_maliyet": manual_cost,
                    "kar": 0 - manual_cost - (booking.kms or 0),
                },
                update_modified=False,
            )
            repaired_non_umreci += 1

    # Any records not identified as non-paying should be paying customers. Keep this
    # conservative: only normalize blank/unknown statuses, not deliberate future statuses.
    frappe.db.sql(
        """
        UPDATE `tabUmre Booking`
        SET `statu` = %s, `manual_cost` = NULL
        WHERE (`statu` IS NULL OR `statu` = '')
        """,
        (PAYING_STATUS,),
    )

    # Repopulate missing Diyanet values for paying customers from the existing tour rule.
    # This fixes imported rows whose Diyanet card flag/rule was present but stored cost was zero.
    repaired_diyanet = frappe.db.sql(
        """
        UPDATE `tabUmre Booking` b
        INNER JOIN `tabTour Diyanet Card Rule` r ON r.tur = b.tur
        SET
            b.diyanet_kart_var = 1,
            b.diyanet_maliyeti = IFNULL(r.tutar, 0),
            b.toplam_maliyet = IFNULL(b.otel_maliyeti, 0)
                + IFNULL(b.ucak_maliyeti, 0)
                + IFNULL(b.vize_maliyeti, 0)
                + IFNULL(r.tutar, 0),
            b.kar = IFNULL(b.ucret, 0)
                - (
                    IFNULL(b.otel_maliyeti, 0)
                    + IFNULL(b.ucak_maliyeti, 0)
                    + IFNULL(b.vize_maliyeti, 0)
                    + IFNULL(r.tutar, 0)
                )
                - IFNULL(b.kms, 0)
        WHERE b.statu = %s
          AND IFNULL(b.diyanet_maliyeti, 0) = 0
          AND IFNULL(r.tutar, 0) > 0
        """,
        (PAYING_STATUS,),
    )

    _log("repair complete", {"non_umreci_rows": repaired_non_umreci, "diyanet_update_result": repaired_diyanet})
