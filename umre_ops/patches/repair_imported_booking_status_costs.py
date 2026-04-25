# Copyright (c) 2026, Sermed Turizm
# Repair corrupted import mappings for booking status/manual cost.

from __future__ import annotations

import frappe
from frappe.utils import flt


PAYING_STATUS = "UMRECI"
SOURCE_REPAIRS = [
    {"tc_kimlik": "10205468208", "statu": "HOCA", "manual_cost": 1223.0},
    {"tc_kimlik": "29726548610", "statu": "HOCA_ESI", "manual_cost": 1223.0},
    {"tc_kimlik": "40240144324", "statu": "HOCA_COCUGU", "manual_cost": 700.0},
    {"tc_kimlik": "66016043950", "statu": "FREE", "manual_cost": 1080.0},
]


def execute() -> None:
    repaired = 0
    for source in SOURCE_REPAIRS:
        umreci_names = frappe.get_all("Umreci", filters={"tc_kimlik": source["tc_kimlik"]}, pluck="name")
        if not umreci_names:
            continue
        bookings = frappe.get_all("Umre Booking", filters={"umreci": ["in", umreci_names]}, pluck="name")
        for booking_name in bookings:
            booking = frappe.get_doc("Umre Booking", booking_name)
            manual_cost = flt(source["manual_cost"])
            kms = flt(booking.get("kms") or 0)
            frappe.db.set_value(
                "Umre Booking",
                booking.name,
                {
                    "statu": source["statu"],
                    "ucret": 0,
                    "odenen": 0,
                    "manual_cost": manual_cost,
                    "otel_maliyeti": 0,
                    "ucak_maliyeti": 0,
                    "vize_maliyeti": 0,
                    "diyanet_maliyeti": 0,
                    "toplam_maliyet": manual_cost,
                    "kar": 0 - manual_cost - kms,
                },
                update_modified=False,
            )
            repaired += 1

    diyanet_repaired = _repair_umreci_diyanet_costs()
    frappe.db.commit()
    print(
        "repair_imported_booking_status_costs: "
        f"non_umreci_repaired={repaired}, umreci_diyanet_repaired={diyanet_repaired}"
    )


def _repair_umreci_diyanet_costs() -> int:
    repaired = 0
    bookings = frappe.get_all(
        "Umre Booking",
        filters={"statu": PAYING_STATUS},
        fields=["name", "tur", "diyanet_maliyeti", "toplam_maliyet", "kar"],
    )
    for booking in bookings:
        amount = flt(frappe.db.get_value("Tour Diyanet Card Rule", {"tur": booking.tur}, "tutar") or 0)
        if amount <= 0 or flt(booking.diyanet_maliyeti) != 0:
            continue
        frappe.db.set_value(
            "Umre Booking",
            booking.name,
            {
                "diyanet_kart_var": 1,
                "diyanet_maliyeti": amount,
                "toplam_maliyet": flt(booking.toplam_maliyet) + amount,
                "kar": flt(booking.kar) - amount,
            },
            update_modified=False,
        )
        repaired += 1
    return repaired
