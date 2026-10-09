from types import SimpleNamespace
from unittest import TestCase

from umre_ops.umre_ops.services import cost_engine
from umre_ops.umre_ops.services.cost_engine import TourCostContext, compute_cost_lines, summarize_lines
from umre_ops.umre_ops.services.tour_cost_rule_service import apply_tour_hotel_rule_derived_fields


def hotel_rule(nights: int, room_price_sar: float, sar_per_usd: float = 3.75) -> SimpleNamespace:
	doc = SimpleNamespace(gece_sayisi=nights, birim_fiyat_sar=room_price_sar, kur=sar_per_usd)
	apply_tour_hotel_rule_derived_fields(doc)
	return doc


def context(*hotel_rules: SimpleNamespace, **overrides) -> TourCostContext:
	ctx = TourCostContext(tour="TUR-1")
	ctx.hotel_rule_count = len(hotel_rules)
	for capacity, fieldname in cost_engine._HOTEL_FIELD_BY_CAPACITY.items():
		ctx.hotel_per_person[capacity] = round(sum(getattr(r, fieldname) for r in hotel_rules), 2)
	ctx.airfare = {"Normal": 700.0, "Çocuk": 550.0, "Bebek": 120.0}
	ctx.visa = {"Umre": 150.0}
	ctx.diyanet = 40.0
	for key, value in overrides.items():
		setattr(ctx, key, value)
	return ctx


def booking(**values) -> dict:
	base = {
		"name": "UMB-1",
		"tur": "TUR-1",
		"statu": "UMRECI",
		"cost_policy": "System Rules",
		"oda_tipi": "2 Kişilik",
		"yolcu_tipi": "Normal",
		"vize_tipi": "Umre",
		"manual_cost": 0,
		"iptal_edildi": 0,
	}
	base.update(values)
	return base


class TestHotelShare(TestCase):
	def test_room_price_is_split_by_capacity(self) -> None:
		# Medine: 400 SAR/day room, 5 nights, 3.75 SAR per USD -> room total 533.33 USD.
		ctx = context(hotel_rule(5, 400))
		for oda_tipi, expected in (("1 Kişilik", 533.33), ("2 Kişilik", 266.67), ("4 Kişilik", 133.33)):
			lines, _issues = compute_cost_lines(booking(oda_tipi=oda_tipi), ctx)
			self.assertEqual(summarize_lines(lines)["HOTEL"], expected, oda_tipi)

	def test_mekke_and_medine_rules_are_summed(self) -> None:
		ctx = context(hotel_rule(4, 600), hotel_rule(5, 400))
		lines, _issues = compute_cost_lines(booking(oda_tipi="2 Kişilik"), ctx)
		self.assertEqual(summarize_lines(lines)["HOTEL"], round(4 * 600 / 3.75 / 2 + 5 * 400 / 3.75 / 2, 2))

	def test_children_and_babies_pay_no_hotel(self) -> None:
		ctx = context(hotel_rule(5, 400))
		for yolcu_tipi, flight in (("Çocuk", 550.0), ("Bebek", 120.0)):
			lines, issues = compute_cost_lines(booking(yolcu_tipi=yolcu_tipi), ctx)
			totals = summarize_lines(lines)
			self.assertNotIn("HOTEL", totals)
			self.assertEqual(totals["FLIGHT"], flight)
			self.assertEqual(totals["VISA"], 150.0)
			self.assertEqual(totals["DIYANET"], 40.0)
			self.assertEqual(issues, [])


class TestCostLines(TestCase):
	def test_meal_and_other_apply_to_every_passenger(self) -> None:
		ctx = context(hotel_rule(5, 400), meal_per_person=80.0, other_per_person=25.0)
		for yolcu_tipi in ("Normal", "Çocuk", "Bebek"):
			totals = summarize_lines(compute_cost_lines(booking(yolcu_tipi=yolcu_tipi), ctx)[0])
			self.assertEqual(totals["MEAL"], 80.0)
			self.assertEqual(totals["OTHER"], 25.0)

	def test_missing_rule_reports_issue_instead_of_zero_line(self) -> None:
		ctx = context(hotel_rule(5, 400), airfare={"Normal": 700.0})
		lines, issues = compute_cost_lines(booking(yolcu_tipi="Çocuk"), ctx)
		self.assertNotIn("FLIGHT", summarize_lines(lines))
		self.assertIn({"code": "MISSING_RULE", "cost_type": "FLIGHT", "detail": "Çocuk"}, issues)

	def test_missing_hotel_rules_report_issue(self) -> None:
		lines, issues = compute_cost_lines(booking(), context())
		self.assertNotIn("HOTEL", summarize_lines(lines))
		self.assertEqual(issues[0]["code"], "MISSING_RULE")
		self.assertEqual(issues[0]["cost_type"], "HOTEL")

	def test_zero_rule_reports_issue(self) -> None:
		lines, issues = compute_cost_lines(booking(), context(hotel_rule(5, 400), diyanet=0.0))
		self.assertNotIn("DIYANET", summarize_lines(lines))
		self.assertIn({"code": "ZERO_RULE", "cost_type": "DIYANET", "detail": None}, issues)

	def test_cancelled_booking_has_no_cost(self) -> None:
		self.assertEqual(compute_cost_lines(booking(iptal_edildi=1), context(hotel_rule(5, 400))), ([], []))

	def test_free_status_with_system_rules_carries_full_cost(self) -> None:
		totals = summarize_lines(compute_cost_lines(booking(statu="HOCA"), context(hotel_rule(5, 400)))[0])
		self.assertEqual(set(totals), {"HOTEL", "FLIGHT", "VISA", "DIYANET"})

	def test_legacy_manual_policy_uses_manual_cost(self) -> None:
		lines, issues = compute_cost_lines(
			booking(statu="FREE", cost_policy="Legacy Manual", manual_cost=900), context()
		)
		self.assertEqual(summarize_lines(lines), {"MANUAL": 900.0})
		self.assertEqual(issues, [])
		_lines, issues = compute_cost_lines(booking(statu="FREE", cost_policy="Legacy Manual"), context())
		self.assertEqual(issues[0]["code"], "MANUAL_COST_MISSING")

	def test_invalid_meal_rate_is_an_issue_not_a_crash(self) -> None:
		ctx = context(hotel_rule(5, 400))
		ctx.nights = {"Mekke": 4, "Medine": 5}
		cost_engine._apply_meal_rule(ctx, {"name": "MEAL-1", "mekke_price_sar": 30, "medine_price_sar": 25, "sar_to_usd_rate": 0})
		lines, issues = compute_cost_lines(booking(), ctx)
		self.assertNotIn("MEAL", summarize_lines(lines))
		self.assertIn({"code": "INVALID_RATE", "cost_type": "MEAL", "rule": "MEAL-1"}, issues)

	def test_meal_per_person_uses_hotel_nights(self) -> None:
		ctx = context()
		ctx.nights = {"Mekke": 4, "Medine": 5}
		cost_engine._apply_meal_rule(ctx, {"name": "MEAL-1", "mekke_price_sar": 30, "medine_price_sar": 24, "sar_to_usd_rate": 3.75})
		self.assertEqual(ctx.meal_per_person, round((4 * 30 + 5 * 24) / 3.75, 2))

	def test_diff_detects_stale_components(self) -> None:
		ctx = context(hotel_rule(5, 400))
		fresh = cost_engine.diff_components(booking(), ctx, {"HOTEL": 266.67, "FLIGHT": 700.0, "VISA": 150.0, "DIYANET": 40.0})
		self.assertFalse(fresh["stale"])
		stale = cost_engine.diff_components(booking(yolcu_tipi="Bebek"), ctx, {"HOTEL": 266.67, "FLIGHT": 700.0, "VISA": 150.0, "DIYANET": 40.0})
		self.assertTrue(stale["stale"])
