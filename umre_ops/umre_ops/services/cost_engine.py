# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Component-based cost engine.

Public surface
==============
* ``CANONICAL_TYPES``                                        — system-managed type codes
* ``compute_cost(booking)``                                  — sum of component amounts
* ``get_cost_components(booking)``                           — raw component list
* ``cost_breakdown(booking)``                                — dict(cost_type_code -> total)
* ``generate_components(booking, *, replace_system_generated=False)``
                                                              — idempotent insert
* ``recompute_components(booking)``                          — alias with replace=True
* ``assert_components_valid(booking)``                       — integrity guard
* ``ensure_canonical_cost_types()``                          — seed master rows

Design rules
------------
* Components are persisted ``Cost Component`` rows. They are the single
  source of truth for booking cost; the legacy ``otel/ucak/vize/diyanet``
  columns on ``Umre Booking`` are deprecated and not read by any service.
* Generation is **one-shot** per booking. After insert we never silently
  refresh; ``replace_system_generated=True`` is the only sanctioned path
  (called by the migration patch and an explicit ops action).
* Every component carries its own ``currency``; cross-currency sums are
  forbidden and will raise.
* All system-managed components are emitted even when their amount is 0
  (e.g. DIYANET when the card flag is off, OTHER when not configured) so
  the per-tour breakdown always carries the same column set.
"""
from __future__ import annotations

import re
from typing import Iterable

import frappe
from frappe import _
from frappe.utils import cint, flt

PAYING_STATUS = "UMRECI"
UCAK_COMPONENT = "U\u00e7ak"

# Canonical, system-managed cost types (immutable order in the report).
CANONICAL_TYPES: list[dict] = [
	{"code": "HOTEL",   "name": "Otel Maliyeti",    "sort": 10, "is_system_managed": 1},
	{"code": "FLIGHT",  "name": "U\u00e7ak Maliyeti", "sort": 20, "is_system_managed": 1},
	{"code": "VISA",    "name": "Vize Maliyeti",    "sort": 30, "is_system_managed": 1},
	{"code": "DIYANET", "name": "Diyanet Maliyeti", "sort": 40, "is_system_managed": 1},
	{"code": "MEAL",    "name": "Yemek Maliyeti",   "sort": 50, "is_system_managed": 1},
	{"code": "OTHER",   "name": "Di\u011fer Maliyet", "sort": 60, "is_system_managed": 1},
	{"code": "MANUAL",  "name": "Manuel Maliyet",   "sort": 90, "is_system_managed": 1},
]
SYSTEM_TYPES_FOR_UMRECI: tuple[str, ...] = ("HOTEL", "FLIGHT", "VISA", "DIYANET", "MEAL", "OTHER")
SYSTEM_TYPES_FOR_NON_UMRECI: tuple[str, ...] = ("MANUAL",)


# ---------------------------------------------------------------------------
# Master seeding
# ---------------------------------------------------------------------------

def ensure_canonical_cost_types() -> None:
	"""Idempotently materialize the canonical Cost Type master rows."""
	for spec in CANONICAL_TYPES:
		code = spec["code"]
		if frappe.db.exists("Cost Type", code):
			# Keep system flags and sort_order in sync if drifted.
			frappe.db.set_value(
				"Cost Type",
				code,
				{
					"cost_type_name": spec["name"],
					"is_system_managed": spec["is_system_managed"],
					"sort_order": spec["sort"],
					"default_currency": "USD",
					"is_revenue_negating": 1,
				},
				update_modified=False,
			)
			continue
		doc = frappe.get_doc({
			"doctype": "Cost Type",
			"cost_type_code": code,
			"cost_type_name": spec["name"],
			"is_system_managed": spec["is_system_managed"],
			"is_revenue_negating": 1,
			"default_currency": "USD",
			"sort_order": spec["sort"],
			"description": "Canonical system-managed cost type.",
		})
		doc.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Pure tour lookups (used by the meal / other-cost generators)
# ---------------------------------------------------------------------------

def _parse_oda_index(oda_tipi: str | None) -> int:
	if not oda_tipi:
		return 1
	m = re.match(r"^(\d+)", str(oda_tipi).strip())
	if m:
		return min(max(int(m.group(1)), 1), 4)
	return 1


def _hotel_field_for_oda(idx: int) -> str:
	return {
		1: "bir_kisilik_oda_maaliyeti",
		2: "iki_kisilik_oda_maliyeti",
		3: "uc_kisilik_oda_maliyeti",
		4: "dort_kisilik_oda_maliyeti",
	}[idx]


def _hotel_total(tur: str | None, oda_tipi: str | None) -> float:
	if not tur:
		return 0.0
	idx = _parse_oda_index(oda_tipi)
	field = _hotel_field_for_oda(idx)
	rules = frappe.get_all("Tour Hotel Cost Rule", filters={"tur": tur}, pluck="name")
	total = 0.0
	for rname in rules:
		row = frappe.db.get_value("Tour Hotel Cost Rule", rname, [field], as_dict=True)
		if row and row.get(field) is not None:
			total += flt(row[field])
	return flt(total)


def _flight_total(tur: str | None, yolcu_tipi: str | None) -> float:
	if not (tur and yolcu_tipi):
		return 0.0
	name = frappe.db.get_value(
		"Tour Passenger Cost Rule",
		{"tur": tur, "yolcu_tipi": yolcu_tipi, "expense_component": UCAK_COMPONENT},
		"name",
	)
	if not name:
		return 0.0
	return flt(frappe.db.get_value("Tour Passenger Cost Rule", name, "tutar") or 0)


def _visa_total(tur: str | None, vize_tipi: str | None) -> float:
	if not (tur and vize_tipi):
		return 0.0
	name = frappe.db.get_value(
		"Tour Visa Cost Rule",
		{"tur": tur, "vize_tipi": vize_tipi},
		"name",
	)
	if not name:
		return 0.0
	return flt(frappe.db.get_value("Tour Visa Cost Rule", name, "tutar") or 0)


def _diyanet_total(tur: str | None, has_card: int | None) -> float:
	if not tur or not cint(has_card):
		return 0.0
	name = frappe.db.get_value("Tour Diyanet Card Rule", {"tur": tur}, "name")
	if not name:
		return 0.0
	return flt(frappe.db.get_value("Tour Diyanet Card Rule", name, "tutar") or 0)


def _meal_inputs(tour_doc) -> dict:
	return {
		"mekke_days":            cint(tour_doc.get("mekke_days") or 0),
		"medine_days":           cint(tour_doc.get("medine_days") or 0),
		"mekke_meal_price_sar":  flt(tour_doc.get("mekke_meal_price_sar") or 0),
		"medine_meal_price_sar": flt(tour_doc.get("medine_meal_price_sar") or 0),
		"sar_to_usd_rate":       flt(tour_doc.get("sar_to_usd_rate") or 0),
	}


def _meal_total_usd(tour_doc) -> tuple[float, str]:
	"""(amount in USD, human description)."""
	m = _meal_inputs(tour_doc)
	if not (m["mekke_days"] or m["medine_days"]):
		return 0.0, "no meal days configured"
	if (m["mekke_meal_price_sar"] or m["medine_meal_price_sar"]) and not m["sar_to_usd_rate"]:
		# Fail-fast: SAR config without an FX rate is a configuration error.
		frappe.throw(
			_("Tour {0}: meal prices in SAR are configured but `sar_to_usd_rate` is 0. "
			  "Set the conversion rate before booking UMRECI participants.").format(tour_doc.name)
		)
	if m["sar_to_usd_rate"] <= 0:
		return 0.0, "no FX rate"
	sar = (
		m["mekke_days"] * m["mekke_meal_price_sar"]
		+ m["medine_days"] * m["medine_meal_price_sar"]
	)
	usd = flt(sar / m["sar_to_usd_rate"])
	desc = (
		f"({m['mekke_days']}d Mekke x {m['mekke_meal_price_sar']:.2f} SAR + "
		f"{m['medine_days']}d Medine x {m['medine_meal_price_sar']:.2f} SAR) "
		f"/ {m['sar_to_usd_rate']:.4f}"
	)
	return flt(round(usd, 2)), desc


def _other_total(tour_doc) -> float:
	return flt(tour_doc.get("other_cost_per_person") or 0)


# ---------------------------------------------------------------------------
# Component access
# ---------------------------------------------------------------------------

def _booking_currency(booking) -> str:
	"""Currency of the booking's tour. Falls back to USD for safety."""
	tur = booking.get("tur") if isinstance(booking, dict) else getattr(booking, "tur", None)
	if not tur:
		return "USD"
	curr = frappe.db.get_value("Umre Tour", tur, "para_birimi")
	return curr or "USD"


def get_cost_components(booking) -> list[dict]:
	booking_name = booking if isinstance(booking, str) else (
		booking.get("name") if isinstance(booking, dict) else getattr(booking, "name", None)
	)
	if not booking_name:
		return []
	return frappe.get_all(
		"Cost Component",
		filters={"booking": booking_name},
		fields=["name", "cost_type", "description", "quantity", "unit_price",
		        "amount", "currency", "is_system_generated", "source"],
		order_by="cost_type asc, creation asc",
	)


def compute_cost(booking) -> float:
	"""Sum of all component amounts. Refuses to mix currencies silently."""
	comps = get_cost_components(booking)
	if not comps:
		return 0.0
	currencies = {c["currency"] for c in comps if c.get("currency")}
	if len(currencies) > 1:
		frappe.throw(
			_("Booking {0} has cost components in multiple currencies ({1}). "
			  "The cost engine refuses silent FX conversion at sum time.").format(
				booking if isinstance(booking, str) else getattr(booking, "name", "?"),
				", ".join(sorted(currencies)),
			)
		)
	return flt(sum(flt(c["amount"] or 0) for c in comps))


def cost_breakdown(booking) -> dict[str, float]:
	"""Component sums grouped by cost_type code. Includes all canonical types
	with 0 if the booking does not carry that component."""
	totals = {spec["code"]: 0.0 for spec in CANONICAL_TYPES}
	for c in get_cost_components(booking):
		ct = c["cost_type"]
		totals.setdefault(ct, 0.0)
		totals[ct] = flt(totals[ct] + flt(c["amount"] or 0))
	return totals


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _make_component(
	*,
	booking_name: str,
	tour: str | None,
	cost_type: str,
	description: str,
	quantity: float,
	unit_price: float,
	currency: str,
	source: str,
	notes: str | None = None,
) -> str:
	"""Insert a system-generated Cost Component. Returns the new doc name."""
	amount = flt(round(flt(quantity) * flt(unit_price), 2))
	doc = frappe.get_doc({
		"doctype": "Cost Component",
		"booking": booking_name,
		"tour": tour,
		"cost_type": cost_type,
		"description": description,
		"quantity": flt(quantity),
		"unit_price": flt(unit_price),
		"amount": amount,
		"currency": currency,
		"is_system_generated": 1,
		"source": source,
		"notes": notes or None,
	})
	doc.flags.ignore_system_generated_lock = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _delete_system_generated(booking_name: str) -> int:
	names = frappe.get_all(
		"Cost Component",
		filters={"booking": booking_name, "is_system_generated": 1},
		pluck="name",
	)
	for n in names:
		frappe.delete_doc("Cost Component", n, force=1, ignore_permissions=True)
	return len(names)


def generate_components(
	booking,
	*,
	replace_system_generated: bool = False,
) -> list[str]:
	"""Idempotent component generation for a single booking.

	If components already exist and ``replace_system_generated`` is False, this
	is a no-op (returns []). When True, all existing system-generated rows are
	deleted first; manually-added components are preserved.
	"""
	ensure_canonical_cost_types()

	# Resolve the booking doc so we always have the freshest field values.
	if isinstance(booking, str):
		booking_doc = frappe.get_doc("Umre Booking", booking)
	elif isinstance(booking, dict):
		booking_doc = frappe.get_doc("Umre Booking", booking["name"])
	else:
		booking_doc = booking
		if not booking_doc.name:
			frappe.throw(_("generate_components: booking must be a saved document."))

	booking_name = booking_doc.name
	tour_name = booking_doc.get("tur")

	existing = frappe.db.count(
		"Cost Component", {"booking": booking_name, "is_system_generated": 1}
	)
	if existing and not replace_system_generated:
		return []
	if replace_system_generated:
		_delete_system_generated(booking_name)

	tour_doc = frappe.get_doc("Umre Tour", tour_name) if tour_name and frappe.db.exists("Umre Tour", tour_name) else None
	currency = (tour_doc.para_birimi if tour_doc else None) or _booking_currency(booking_doc)

	statu = (booking_doc.get("statu") or PAYING_STATUS).strip() or PAYING_STATUS
	created: list[str] = []

	if statu == PAYING_STATUS:
		# 1) HOTEL — sum all hotel rules for this tour at the booked oda_tipi.
		hotel = _hotel_total(tour_name, booking_doc.get("oda_tipi"))
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="HOTEL",
			description=f"Otel ({booking_doc.get('oda_tipi') or '1 Kişilik'})",
			quantity=1, unit_price=hotel, currency=currency,
			source="tour_hotel_cost_rule",
		))
		# 2) FLIGHT — passenger rule for this tour + yolcu_tipi.
		flight = _flight_total(tour_name, booking_doc.get("yolcu_tipi"))
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="FLIGHT",
			description=f"Uçak ({booking_doc.get('yolcu_tipi') or '?'})",
			quantity=1, unit_price=flight, currency=currency,
			source="tour_passenger_cost_rule",
		))
		# 3) VISA — visa rule for this tour + vize_tipi.
		visa = _visa_total(tour_name, booking_doc.get("vize_tipi"))
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="VISA",
			description=f"Vize ({booking_doc.get('vize_tipi') or '?'})",
			quantity=1, unit_price=visa, currency=currency,
			source="tour_visa_cost_rule",
		))
		# 4) DIYANET — only when card flag is set; emit 0 otherwise so the
		#    column always exists in the breakdown.
		diy = _diyanet_total(tour_name, booking_doc.get("diyanet_kart_var"))
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="DIYANET",
			description="Diyanet kart" if cint(booking_doc.get("diyanet_kart_var")) else "Diyanet kart yok",
			quantity=1, unit_price=diy, currency=currency,
			source="tour_diyanet_card_rule",
		))
		# 5) MEAL — derived from per-tour days/prices and SAR→USD FX.
		if not tour_doc:
			frappe.throw(_("Booking {0}: tour {1} is not resolvable; cannot compute MEAL component.").format(booking_name, tour_name))
		meal_amount, meal_desc = _meal_total_usd(tour_doc)
		mealinp = _meal_inputs(tour_doc)
		mekke_days = mealinp["mekke_days"]
		medine_days = mealinp["medine_days"]
		mekke_unit = flt(mealinp["mekke_meal_price_sar"]) / mealinp["sar_to_usd_rate"] if mealinp["sar_to_usd_rate"] else 0
		medine_unit = flt(mealinp["medine_meal_price_sar"]) / mealinp["sar_to_usd_rate"] if mealinp["sar_to_usd_rate"] else 0
		# Represent meal as a single composite component (qty=1, unit_price=amount)
		# because mekke and medine days carry different unit prices. Composition
		# detail is preserved in `description`.
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="MEAL",
			description=f"Yemek {meal_desc}",
			quantity=1, unit_price=meal_amount, currency=currency,
			source="meal_engine",
			notes=(f"mekke_days={mekke_days} mekke_unit_usd={mekke_unit:.4f}; "
			       f"medine_days={medine_days} medine_unit_usd={medine_unit:.4f}"),
		))
		# 6) OTHER — flat per-tour amount.
		other = _other_total(tour_doc)
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="OTHER",
			description="Diğer (transfer / hediye)",
			quantity=1, unit_price=other, currency=currency,
			source="umre_tour.other_cost_per_person",
		))
	else:
		# Non-UMRECI: a single MANUAL component carrying `manual_cost`.
		manual = flt(booking_doc.get("manual_cost") or 0)
		if manual <= 0:
			frappe.throw(
				_("Booking {0} has statu {1} but `manual_cost` is 0. "
				  "Non-UMRECI bookings MUST carry a positive manual cost.").format(
					booking_name, statu
				)
			)
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="MANUAL",
			description=f"Manuel maliyet ({statu})",
			quantity=1, unit_price=manual, currency=currency,
			source="umre_booking.manual_cost",
		))

	return created


def recompute_components(booking) -> list[str]:
	"""Explicit refresh: deletes existing system-generated rows and rebuilds."""
	created = generate_components(booking, replace_system_generated=True)
	# Nudge any open Umre Operasyon Paneli even when components are unchanged.
	try:
		from umre_ops.umre_ops.services.dashboard_service import publish_dashboard_dirty
		name = booking if isinstance(booking, str) else getattr(booking, "name", None)
		tour = frappe.db.get_value("Umre Booking", name, "tur") if name else None
		publish_dashboard_dirty(tour)
	except Exception:
		frappe.log_error(title="dashboard publish failed (recompute)")
	return created


@frappe.whitelist()
def recompute_components_for_booking(booking_name: str) -> dict:
	"""Whitelisted desk action: refresh components for a single booking."""
	if not frappe.has_permission("Umre Booking", "write", doc=booking_name):
		frappe.throw(_("Not permitted to recompute components for {0}").format(booking_name))
	created = recompute_components(booking_name)
	return {"booking": booking_name, "components_created": created}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def assert_components_valid(booking) -> None:
	"""Hard-check: booking must have the required components for its statu."""
	booking_name = booking if isinstance(booking, str) else getattr(booking, "name", None)
	if not booking_name:
		return
	statu_value = (
		booking
		if not isinstance(booking, str)
		else None
	)
	statu = (
		(getattr(statu_value, "statu", None) if statu_value is not None else None)
		or frappe.db.get_value("Umre Booking", booking_name, "statu")
		or PAYING_STATUS
	)
	required: Iterable[str] = (
		SYSTEM_TYPES_FOR_UMRECI if statu == PAYING_STATUS else SYSTEM_TYPES_FOR_NON_UMRECI
	)

	present = {
		c["cost_type"]
		for c in frappe.get_all(
			"Cost Component",
			filters={"booking": booking_name, "is_system_generated": 1},
			fields=["cost_type"],
		)
	}
	missing = [t for t in required if t not in present]
	if missing:
		frappe.throw(
			_("Booking {0} is missing required cost components: {1}").format(
				booking_name, ", ".join(missing)
			)
		)
	# No negative components.
	bad = frappe.db.sql(
		"SELECT name, cost_type, amount FROM `tabCost Component` WHERE booking=%s AND amount < 0",
		(booking_name,),
		as_dict=True,
	)
	if bad:
		frappe.throw(
			_("Booking {0} has negative cost components: {1}").format(
				booking_name, ", ".join(f"{b['name']}={b['amount']}" for b in bad)
			)
		)
