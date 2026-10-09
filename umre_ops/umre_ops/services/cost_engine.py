# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Component-based cost engine — the single source of booking cost.

Public surface
==============
* ``CANONICAL_TYPES``                                   — system-managed type codes
* ``load_tour_cost_context(tour)``                      — all cost rules of a tour, loaded once
* ``compute_cost_lines(booking, ctx)``                  — pure: expected lines + issues
* ``booking_cost_inputs(booking)``                      — the booking fields the engine reads
* ``compute_cost(booking)`` / ``cost_breakdown(booking)`` — persisted component sums
* ``generate_components(booking, *, replace_system_generated=False)``
* ``recompute_components(booking)``                     — explicit refresh (replace=True)
* ``diff_components(booking, ctx)``                     — stored vs expected (staleness)
* ``recompute_tour_bookings(tour)``                     — full replace + per-booking commit
* ``schedule_recompute_for_tour(tour)``                 — RQ, deduplicated per tour

Business rules (confirmed by operations)
----------------------------------------
* Everything is costed in USD. SAR rules carry their own SAR→USD rate.
* HOTEL: per-person share = room price / capacity, summed over the tour's hotel
  rules (Mekke, Medine, ...). Only ``yolcu_tipi == "Normal"`` pays hotel;
  children (Çocuk) and babies (Bebek) do not.
* FLIGHT by ``yolcu_tipi``, VISA by ``vize_tipi``, DIYANET per passenger.
* MEAL / OTHER apply to every passenger when the tour has that rule.
* A cancelled booking (``iptal_edildi``) carries no cost.
* A missing or zero rule never produces a silent 0 line: no line is created and
  an issue (``MISSING_RULE`` / ``ZERO_RULE`` / ``INVALID_RATE``) is reported so
  dashboards and import previews can show it.
* Components of a booking whose cost Journal Entry is submitted are frozen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt

PAYING_STATUS = "UMRECI"
SYSTEM_RULES_POLICY = "System Rules"
HOTEL_PAYING_PASSENGER_TYPES = frozenset({"Normal"})
COST_CURRENCY = "USD"

# Canonical, system-managed cost types (immutable order in the report).
CANONICAL_TYPES: list[dict] = [
	{"code": "HOTEL", "name": "Otel Maliyeti", "sort": 10, "is_system_managed": 1},
	{"code": "FLIGHT", "name": "Uçak Maliyeti", "sort": 20, "is_system_managed": 1},
	{"code": "VISA", "name": "Vize Maliyeti", "sort": 30, "is_system_managed": 1},
	{"code": "DIYANET", "name": "Diyanet Maliyeti", "sort": 40, "is_system_managed": 1},
	{"code": "MEAL", "name": "Yemek Maliyeti", "sort": 50, "is_system_managed": 1},
	{"code": "OTHER", "name": "Diğer Maliyet", "sort": 60, "is_system_managed": 1},
	{"code": "MANUAL", "name": "Manuel Maliyet", "sort": 90, "is_system_managed": 1},
]

# Booking fields that change the computed cost. A change to any of these
# triggers a recompute (see ``Umre Booking.on_update``).
COST_DRIVER_FIELDS: tuple[str, ...] = (
	"tur",
	"oda_tipi",
	"yolcu_tipi",
	"vize_tipi",
	"statu",
	"cost_policy",
	"manual_cost",
	"iptal_edildi",
)

_HOTEL_FIELD_BY_CAPACITY = {
	1: "bir_kisilik_oda_maaliyeti",
	2: "iki_kisilik_oda_maliyeti",
	3: "uc_kisilik_oda_maliyeti",
	4: "dort_kisilik_oda_maliyeti",
}


# ---------------------------------------------------------------------------
# Master seeding
# ---------------------------------------------------------------------------

def ensure_canonical_cost_types() -> None:
	"""Create missing canonical Cost Type rows (once per request/job).

	Existing rows are not rewritten: operators may rename or reorder them.
	"""
	if frappe.flags.get("umre_canonical_cost_types_ok"):
		return
	for spec in CANONICAL_TYPES:
		if frappe.db.exists("Cost Type", spec["code"]):
			continue
		frappe.get_doc({
			"doctype": "Cost Type",
			"cost_type_code": spec["code"],
			"cost_type_name": spec["name"],
			"is_system_managed": spec["is_system_managed"],
			"is_revenue_negating": 1,
			"default_currency": COST_CURRENCY,
			"sort_order": spec["sort"],
			"description": "Canonical system-managed cost type.",
		}).insert(ignore_permissions=True)
	frappe.flags.umre_canonical_cost_types_ok = True


# ---------------------------------------------------------------------------
# Tour cost context (all rules of one tour, loaded once)
# ---------------------------------------------------------------------------

@dataclass
class TourCostContext:
	tour: str | None
	hotel_rule_count: int = 0
	# Per-person USD share by room capacity (1..4), summed over hotel rules.
	hotel_per_person: dict[int, float] = field(default_factory=dict)
	nights: dict[str, int] = field(default_factory=lambda: {"Mekke": 0, "Medine": 0})
	airfare: dict[str, float] = field(default_factory=dict)
	visa: dict[str, float] = field(default_factory=dict)
	diyanet: float | None = None
	meal_per_person: float | None = None
	meal_description: str = ""
	other_per_person: float | None = None
	# Rule-level problems that are not specific to one booking.
	issues: list[dict] = field(default_factory=list)


def _doctype_exists(doctype: str) -> bool:
	return bool(frappe.db.exists("DocType", doctype))


def load_tour_cost_context(tour: str | None) -> TourCostContext:
	"""Read every cost rule of ``tour`` once. Never raises on bad rule data."""
	ctx = TourCostContext(tour=tour)
	if not tour:
		return ctx

	hotel_rows = frappe.get_all(
		"Tour Hotel Cost Rule",
		filters={"tur": tour},
		fields=["name", "lokasyon", "gece_sayisi", *_HOTEL_FIELD_BY_CAPACITY.values()],
		limit_page_length=0,
	)
	ctx.hotel_rule_count = len(hotel_rows)
	for capacity, fieldname in _HOTEL_FIELD_BY_CAPACITY.items():
		ctx.hotel_per_person[capacity] = flt(sum(flt(row.get(fieldname)) for row in hotel_rows), 2)
	for row in hotel_rows:
		if row.get("lokasyon") in ctx.nights:
			ctx.nights[row["lokasyon"]] += cint(row.get("gece_sayisi"))

	for row in frappe.get_all(
		"Tour Airfare Cost Rule",
		filters={"tur": tour},
		fields=["yolcu_tipi", "tutar"],
		order_by="creation asc",
		limit_page_length=0,
	):
		ctx.airfare.setdefault(row.get("yolcu_tipi"), flt(row.get("tutar")))

	for row in frappe.get_all(
		"Tour Visa Cost Rule",
		filters={"tur": tour},
		fields=["vize_tipi", "tutar"],
		order_by="creation asc",
		limit_page_length=0,
	):
		ctx.visa.setdefault(row.get("vize_tipi"), flt(row.get("tutar")))

	diyanet = frappe.db.get_value("Tour Diyanet Card Rule", {"tur": tour}, "tutar")
	if diyanet is not None:
		ctx.diyanet = flt(diyanet)

	if _doctype_exists("Meal Cost Rule"):
		meal = frappe.db.get_value(
			"Meal Cost Rule",
			{"tour": tour},
			["name", "mekke_price_sar", "medine_price_sar", "sar_to_usd_rate"],
			as_dict=True,
		)
		if meal:
			_apply_meal_rule(ctx, meal)

	if _doctype_exists("Other Cost Rule"):
		other = frappe.db.get_value("Other Cost Rule", {"tour": tour}, "per_person_cost")
		if other is not None:
			ctx.other_per_person = flt(other)
	return ctx


def _apply_meal_rule(ctx: TourCostContext, meal: dict) -> None:
	"""Meal per person (USD) = (Mekke nights × Mekke SAR + Medine nights × Medine SAR) / rate."""
	mekke_price = flt(meal.get("mekke_price_sar"))
	medine_price = flt(meal.get("medine_price_sar"))
	rate = flt(meal.get("sar_to_usd_rate"))
	sar_total = ctx.nights["Mekke"] * mekke_price + ctx.nights["Medine"] * medine_price
	ctx.meal_description = (
		f"({ctx.nights['Mekke']}g Mekke x {mekke_price:.2f} SAR + "
		f"{ctx.nights['Medine']}g Medine x {medine_price:.2f} SAR) / {rate:.4f}"
	)
	if sar_total > 0 and rate <= 1:
		ctx.issues.append({"code": "INVALID_RATE", "cost_type": "MEAL", "rule": meal.get("name")})
		ctx.meal_per_person = None
		return
	ctx.meal_per_person = flt(sar_total / rate, 2) if sar_total > 0 else 0.0


# ---------------------------------------------------------------------------
# Pure cost computation
# ---------------------------------------------------------------------------

def _room_capacity(oda_tipi: str | None) -> int:
	match = re.match(r"^\s*(\d+)", str(oda_tipi or ""))
	if not match:
		return 1
	return min(max(int(match.group(1)), 1), 4)


def booking_cost_inputs(booking: Any) -> dict:
	"""Extract the fields the engine reads from a doc / dict / _dict."""
	get = booking.get if hasattr(booking, "get") else lambda key, default=None: getattr(booking, key, default)
	return {
		"name": get("name"),
		"tur": get("tur"),
		"statu": (get("statu") or PAYING_STATUS).strip() or PAYING_STATUS,
		"cost_policy": get("cost_policy"),
		"oda_tipi": get("oda_tipi"),
		"yolcu_tipi": get("yolcu_tipi"),
		"vize_tipi": get("vize_tipi"),
		"manual_cost": flt(get("manual_cost") or 0),
		"iptal_edildi": cint(get("iptal_edildi") or 0),
	}


def _line(cost_type: str, description: str, amount: float, source: str, notes: str | None = None) -> dict:
	return {
		"cost_type": cost_type,
		"description": description,
		"quantity": 1,
		"unit_price": flt(amount, 2),
		"amount": flt(amount, 2),
		"currency": COST_CURRENCY,
		"source": source,
		"notes": notes,
	}


def _issue(code: str, cost_type: str, detail: str | None = None) -> dict:
	return {"code": code, "cost_type": cost_type, "detail": detail}


def _priced_line(
	lines: list[dict],
	issues: list[dict],
	*,
	cost_type: str,
	amount: float | None,
	description: str,
	source: str,
	detail: str | None = None,
	notes: str | None = None,
) -> None:
	"""Append a line for a required rule, or an issue when it is missing / zero."""
	if amount is None:
		issues.append(_issue("MISSING_RULE", cost_type, detail))
	elif flt(amount) <= 0:
		issues.append(_issue("ZERO_RULE", cost_type, detail))
	else:
		lines.append(_line(cost_type, description, amount, source, notes))


def uses_system_rules(inputs: dict) -> bool:
	return inputs["statu"] == PAYING_STATUS or inputs.get("cost_policy") == SYSTEM_RULES_POLICY


def compute_cost_lines(booking: Any, ctx: TourCostContext) -> tuple[list[dict], list[dict]]:
	"""Return ``(lines, issues)`` for one booking. Pure: reads only ``ctx``."""
	inputs = booking_cost_inputs(booking)
	lines: list[dict] = []
	issues: list[dict] = []
	if inputs["iptal_edildi"]:
		return lines, issues

	if not uses_system_rules(inputs):
		manual = flt(inputs["manual_cost"])
		if manual > 0:
			lines.append(_line("MANUAL", f"Manuel maliyet ({inputs['statu']})", manual, "umre_booking.manual_cost"))
		else:
			issues.append(_issue("MANUAL_COST_MISSING", "MANUAL", inputs["statu"]))
		return lines, issues

	yolcu_tipi = inputs.get("yolcu_tipi")
	vize_tipi = inputs.get("vize_tipi")

	if yolcu_tipi in HOTEL_PAYING_PASSENGER_TYPES:
		capacity = _room_capacity(inputs.get("oda_tipi"))
		_priced_line(
			lines, issues,
			cost_type="HOTEL",
			amount=ctx.hotel_per_person.get(capacity) if ctx.hotel_rule_count else None,
			description=f"Otel ({inputs.get('oda_tipi') or '1 Kişilik'})",
			source="tour_hotel_cost_rule",
			detail=inputs.get("oda_tipi"),
		)
	elif not yolcu_tipi:
		issues.append(_issue("MISSING_PASSENGER_TYPE", "HOTEL"))

	_priced_line(
		lines, issues,
		cost_type="FLIGHT",
		amount=ctx.airfare.get(yolcu_tipi) if yolcu_tipi else None,
		description=f"Uçak ({yolcu_tipi or '?'})",
		source="tour_airfare_cost_rule",
		detail=yolcu_tipi,
	)
	_priced_line(
		lines, issues,
		cost_type="VISA",
		amount=ctx.visa.get(vize_tipi) if vize_tipi else None,
		description=f"Vize ({vize_tipi or '?'})",
		source="tour_visa_cost_rule",
		detail=vize_tipi,
	)
	_priced_line(
		lines, issues,
		cost_type="DIYANET",
		amount=ctx.diyanet,
		description="Diyanet (Tour Diyanet Card Rule)",
		source="tour_diyanet_card_rule",
	)
	# MEAL / OTHER are optional per tour: only priced when the tour defines the rule.
	if ctx.meal_per_person is not None and ctx.meal_per_person > 0:
		lines.append(_line(
			"MEAL", f"Yemek {ctx.meal_description}", ctx.meal_per_person,
			"meal_cost_rule+tour_hotel_cost_rule",
			notes=f"mekke_days={ctx.nights['Mekke']} medine_days={ctx.nights['Medine']}",
		))
	if ctx.other_per_person is not None and ctx.other_per_person > 0:
		lines.append(_line("OTHER", "Diğer (kişi başı, Other Cost Rule)", ctx.other_per_person, "other_cost_rule"))
	issues.extend(ctx.issues)
	return lines, issues


def summarize_lines(lines: list[dict]) -> dict[str, float]:
	totals: dict[str, float] = {}
	for line in lines:
		totals[line["cost_type"]] = flt(totals.get(line["cost_type"], 0) + flt(line["amount"]), 2)
	return totals


# ---------------------------------------------------------------------------
# Backwards-compatible helpers (import preflight, integrity checks)
# ---------------------------------------------------------------------------

def required_system_types_for_booking(
	tour: str | None, statu: str, cost_policy: str | None = None, yolcu_tipi: str | None = "Normal"
) -> tuple[str, ...]:
	"""System component types a booking must carry (MEAL/OTHER when the tour has them)."""
	if (statu or "").strip() != PAYING_STATUS and cost_policy != SYSTEM_RULES_POLICY:
		return ("MANUAL",)
	required = ["FLIGHT", "VISA", "DIYANET"]
	if (yolcu_tipi or "Normal") in HOTEL_PAYING_PASSENGER_TYPES:
		required.insert(0, "HOTEL")
	ctx = load_tour_cost_context(tour)
	if ctx.meal_per_person:
		required.append("MEAL")
	if ctx.other_per_person:
		required.append("OTHER")
	return tuple(required)


def validate_component_inputs(booking) -> list[dict]:
	"""Read-only preflight: return the cost issues this booking would have.

	Raises only for the legacy manual policy without a positive manual cost.
	"""
	ctx = load_tour_cost_context(booking.get("tur"))
	_lines, issues = compute_cost_lines(booking, ctx)
	if any(issue["code"] == "MANUAL_COST_MISSING" for issue in issues):
		frappe.throw(_("Non-UMRECI bookings MUST carry a positive manual cost for Legacy Manual policy."))
	return issues


def diyanet_rule_tutar_for_tour(tur: str | None) -> float:
	"""Published per-passenger Diyanet amount from the tour rule (0 if none)."""
	if not tur:
		return 0.0
	return flt(frappe.db.get_value("Tour Diyanet Card Rule", {"tur": tur}, "tutar") or 0)


# ---------------------------------------------------------------------------
# Persisted components
# ---------------------------------------------------------------------------

def _booking_name(booking) -> str | None:
	if isinstance(booking, str):
		return booking
	if isinstance(booking, dict):
		return booking.get("name")
	return getattr(booking, "name", None)


def get_cost_components(booking) -> list[dict]:
	booking_name = _booking_name(booking)
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
				_booking_name(booking) or "?", ", ".join(sorted(currencies))
			)
		)
	return flt(sum(flt(c["amount"] or 0) for c in comps))


def cost_breakdown(booking) -> dict[str, float]:
	"""Component sums grouped by cost_type code (canonical types always present)."""
	totals = {spec["code"]: 0.0 for spec in CANONICAL_TYPES}
	for c in get_cost_components(booking):
		totals[c["cost_type"]] = flt(totals.get(c["cost_type"], 0.0) + flt(c["amount"] or 0))
	return totals


def _insert_component(booking_name: str, tour: str | None, line: dict) -> str:
	doc = frappe.get_doc({
		"doctype": "Cost Component",
		"booking": booking_name,
		"tour": tour,
		"cost_type": line["cost_type"],
		"description": line["description"],
		"quantity": flt(line["quantity"]),
		"unit_price": flt(line["unit_price"]),
		"amount": flt(line["amount"]),
		"currency": line["currency"],
		"is_system_generated": 1,
		"source": line["source"],
		"notes": line.get("notes") or None,
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
	for name in names:
		frappe.delete_doc("Cost Component", name, force=1, ignore_permissions=True)
	return len(names)


def generate_components(
	booking,
	*,
	replace_system_generated: bool = False,
	ctx: TourCostContext | None = None,
) -> list[str]:
	"""Persist the computed lines of one booking.

	Without ``replace_system_generated`` this is a no-op when system rows exist.
	With it, existing system rows are replaced; operator-added rows are kept.
	A booking whose cost Journal Entry is submitted is never replaced.
	"""
	ensure_canonical_cost_types()
	if isinstance(booking, str | dict):
		booking_doc = frappe.get_doc("Umre Booking", _booking_name(booking))
	else:
		booking_doc = booking
		if not booking_doc.name:
			frappe.throw(_("generate_components: booking must be a saved document."))

	booking_name = booking_doc.name
	tour_name = booking_doc.get("tur")
	existing = frappe.db.count("Cost Component", {"booking": booking_name, "is_system_generated": 1})
	if existing and not replace_system_generated:
		return []
	if existing and _has_submitted_cost_posting(booking_name):
		frappe.throw(_("Submitted booking costs cannot be recomputed for {0}.").format(booking_name))

	if ctx is None or ctx.tour != tour_name:
		ctx = load_tour_cost_context(tour_name)
	lines, issues = compute_cost_lines(booking_doc, ctx)
	if any(issue["code"] == "MANUAL_COST_MISSING" for issue in issues):
		frappe.throw(
			_("Booking {0} has statu {1} but `manual_cost` is 0. "
			  "Non-UMRECI bookings MUST carry a positive manual cost.").format(
				booking_name, booking_doc.get("statu")
			)
		)
	if existing:
		_delete_system_generated(booking_name)
	return [_insert_component(booking_name, tour_name, line) for line in lines]


def recompute_components(
	booking, *, skip_dashboard_publish: bool = False, ctx: TourCostContext | None = None
) -> list[str]:
	"""Explicit refresh: replaces system-generated rows with freshly computed ones."""
	created = generate_components(booking, replace_system_generated=True, ctx=ctx)
	if not skip_dashboard_publish:
		try:
			from umre_ops.umre_ops.services.dashboard_service import publish_dashboard_dirty

			name = _booking_name(booking)
			tour = frappe.db.get_value("Umre Booking", name, "tur") if name else None
			publish_dashboard_dirty(tour)
		except Exception:
			frappe.log_error(title="dashboard publish failed (recompute)")
	return created


def diff_components(booking: Any, ctx: TourCostContext, stored: dict[str, float] | None = None) -> dict:
	"""Compare stored system components with the currently expected lines.

	``stored`` may be pre-aggregated by the caller (cost_type -> amount) to avoid
	per-booking queries. Returns ``{"stale": bool, "expected": {...}, "stored": {...}, "issues": [...]}``.
	"""
	lines, issues = compute_cost_lines(booking, ctx)
	expected = summarize_lines(lines)
	if stored is None:
		stored = {}
		for row in frappe.get_all(
			"Cost Component",
			filters={"booking": _booking_name(booking), "is_system_generated": 1},
			fields=["cost_type", "amount"],
		):
			stored[row["cost_type"]] = flt(stored.get(row["cost_type"], 0) + flt(row["amount"]), 2)
	codes = set(expected) | set(stored)
	stale = any(abs(flt(expected.get(code)) - flt(stored.get(code))) > 0.01 for code in codes)
	return {"stale": stale, "expected": expected, "stored": stored, "issues": issues}


# ---------------------------------------------------------------------------
# Tour-wide recompute (RQ)
# ---------------------------------------------------------------------------

def _recompute_job_id(tour: str) -> str:
	return f"umre_recompute_tour::{tour}"


def schedule_recompute_for_tour(tour: str | None) -> None:
	"""Enqueue a full tour recompute after the current commit.

	Deduplicated per tour while a job is queued. If a job is already running it
	may have read the old rules, so a single follow-up job is queued behind it.
	"""
	tour = (tour or "").strip()
	if not tour:
		return
	job_id = _recompute_job_id(tour)
	try:
		from frappe.utils.background_jobs import get_job_status

		if str(get_job_status(job_id) or "") == "started":
			job_id = f"{job_id}::followup"
	except Exception:
		frappe.log_error(title=f"recompute job status check failed: {tour}")
	frappe.enqueue(
		"umre_ops.umre_ops.services.cost_engine.recompute_tour_bookings",
		queue="long",
		timeout=1800,
		tour=tour,
		enqueue_after_commit=True,
		job_id=job_id,
		deduplicate=True,
	)


def schedule_recompute_for_rule(doc) -> None:
	"""Recompute the rule's tour and, when the rule moved, its previous tour too."""
	tour_field = "tur" if doc.meta.has_field("tur") else "tour"
	tours = {doc.get(tour_field)}
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if before is not None:
		tours.add(before.get(tour_field))
	for tour in sorted(t for t in tours if t):
		schedule_recompute_for_tour(tour)


def recompute_tour_bookings(tour: str) -> dict:
	"""Recompute system-generated components for every active booking of ``tour``.

	Rules are loaded once; each booking is committed separately so one failure
	does not roll back the rest. Cancelled bookings lose their system rows.
	"""
	tour = (tour or "").strip()
	if not tour or not frappe.db.exists("Umre Tour", tour):
		return {"tour": tour, "bookings": 0, "ok": 0, "recomputed": 0, "errors": []}
	ctx = load_tour_cost_context(tour)
	names = frappe.get_all("Umre Booking", filters={"tur": tour}, pluck="name", order_by="creation asc")
	errors: list[dict] = []
	skipped_posted: list[str] = []
	for name in names:
		try:
			if not _lock_booking_for_recompute(name):
				continue
			if _has_submitted_cost_posting(name):
				skipped_posted.append(name)
				frappe.db.commit()
				continue
			recompute_components(name, skip_dashboard_publish=True, ctx=ctx)
			frappe.db.commit()
		except Exception as exc:  # noqa: BLE001 — tour batch: collect and continue
			frappe.db.rollback()
			errors.append({"booking": name, "error": str(exc)})
			frappe.log_error(
				message=frappe.get_traceback(),
				title=f"recompute_tour_bookings: tour={tour!r} booking={name!r}",
			)
	try:
		from umre_ops.umre_ops.services.dashboard_service import publish_dashboard_dirty

		publish_dashboard_dirty(tour)
	except Exception:
		frappe.log_error(title="dashboard publish failed (recompute_for_tour)")
	if errors:
		frappe.log_error(
			message=str(errors)[:20000],
			title=f"recompute_tour_bookings: {len(errors)} failed booking(s) on tour={tour!r}",
		)
	return {
		"tour": tour,
		"bookings": len(names),
		"recomputed": len(names) - len(errors) - len(skipped_posted),
		"skipped_posted": skipped_posted,
		"ok": 0 if errors else 1,
		"errors": errors,
	}


def _has_submitted_cost_posting(booking_name: str) -> bool:
	"""Protect the component snapshot used by a submitted cost journal entry."""
	je = frappe.db.get_value(
		"Umre Posting Event",
		{
			"operation": "BOOKING_COSTS_JE",
			"source_doctype": "Umre Booking",
			"source_name": booking_name,
			"status": "Succeeded",
		},
		"result_name",
	)
	return bool(je and frappe.db.get_value("Journal Entry", je, "docstatus") == 1)


def _lock_booking_for_recompute(booking_name: str) -> bool:
	"""Serialize component replacement with accounting posting for this booking."""
	return bool(
		frappe.db.sql(
			"SELECT name FROM `tabUmre Booking` WHERE name = %s FOR UPDATE",
			(booking_name,),
		)
	)


def _require_cost_admin() -> None:
	if frappe.session.user != "Administrator" and "System Manager" not in set(frappe.get_roles()):
		frappe.throw(_("Not permitted to recompute tour costs."), frappe.PermissionError)


@frappe.whitelist()
def recompute_components_for_tour(tour: str) -> dict:
	"""Synchronous, explicit recompute of every booking for a tour (ops / desk)."""
	tour = (tour or "").strip()
	if not tour:
		frappe.throw(_("tour is required."))
	_require_cost_admin()
	if not frappe.has_permission("Umre Tour", "write", doc=tour):
		frappe.throw(_("Not permitted to recompute costs for tour {0}").format(tour))
	booking_names = frappe.get_all("Umre Booking", filters={"tur": tour}, pluck="name")
	if any(not frappe.has_permission("Umre Booking", "write", doc=name) for name in booking_names):
		frappe.throw(
			_("Not permitted to recompute one or more bookings in this tour."),
			frappe.PermissionError,
		)
	return recompute_tour_bookings(tour)


@frappe.whitelist()
def recompute_components_for_booking(booking_name: str) -> dict:
	"""Whitelisted desk action: refresh components for a single booking."""
	if not frappe.has_permission("Umre Booking", "write", doc=booking_name):
		frappe.throw(_("Not permitted to recompute components for {0}").format(booking_name))
	if not _lock_booking_for_recompute(booking_name):
		frappe.throw(_("Umre Booking {0} no longer exists.").format(booking_name))
	created = recompute_components(booking_name)
	return {"booking": booking_name, "components_created": created}


def preview_recompute(season: str | None = None, tour: str | None = None) -> dict:
	"""Read-only: per tour, stored vs expected system cost if everything were recomputed.

	Intended for ``bench execute`` before an approved data refresh. Writes nothing.
	"""
	frappe.only_for("System Manager")
	filters: dict[str, Any] = {}
	if tour:
		filters["name"] = tour
	elif season:
		filters["season"] = season
	result = []
	for tour_name in frappe.get_all("Umre Tour", filters=filters, pluck="name", order_by="name asc"):
		ctx = load_tour_cost_context(tour_name)
		bookings = frappe.get_all(
			"Umre Booking",
			filters={"tur": tour_name},
			fields=["name", *COST_DRIVER_FIELDS],
			limit_page_length=0,
		)
		stored_rows = frappe.get_all(
			"Cost Component",
			filters={"tour": tour_name, "is_system_generated": 1},
			fields=["booking", "cost_type", "amount"],
			limit_page_length=0,
		) if bookings else []
		stored_by_booking: dict[str, dict[str, float]] = {}
		for row in stored_rows:
			bucket = stored_by_booking.setdefault(row["booking"], {})
			bucket[row["cost_type"]] = flt(bucket.get(row["cost_type"], 0) + flt(row["amount"]), 2)
		stale = 0
		stored_total = expected_total = 0.0
		issue_counts: dict[str, int] = {}
		for booking in bookings:
			diff = diff_components(booking, ctx, stored_by_booking.get(booking["name"], {}))
			stale += 1 if diff["stale"] else 0
			stored_total += sum(diff["stored"].values())
			expected_total += sum(diff["expected"].values())
			for issue in diff["issues"]:
				key = f"{issue['code']}:{issue['cost_type']}"
				issue_counts[key] = issue_counts.get(key, 0) + 1
		result.append({
			"tour": tour_name,
			"bookings": len(bookings),
			"stale_bookings": stale,
			"stored_system_cost": flt(stored_total, 2),
			"expected_system_cost": flt(expected_total, 2),
			"difference": flt(expected_total - stored_total, 2),
			"issues": issue_counts,
		})
	return {"tours": result}
