from unittest import TestCase

from umre_ops.umre_ops.services.cost_engine import TourCostContext
from umre_ops.umre_ops.services.pnl_service import build_pnl

TOURS = [
	{"name": "TUR-A", "label": "Şevval A", "durum": "Aktif"},
	{"name": "TUR-X", "label": "İptal Tur", "durum": "İptal"},
]


def booking(name: str, **values) -> dict:
	row = {
		"name": name, "tur": "TUR-A", "statu": "UMRECI", "ucret": 1300, "kms": 0, "odenen": 0,
		"bildirilen_odenen": 0, "company": "Sermed", "iptal_edildi": 0, "oda_tipi": "2 Kişilik",
		"yolcu_tipi": "Normal", "vize_tipi": "Umre", "cost_policy": "System Rules", "manual_cost": 0,
	}
	row.update(values)
	return row


def comps(booking_name: str, **amounts) -> list[dict]:
	return [
		{"booking": booking_name, "cost_type": code, "currency": "USD", "amount": amount, "is_system_generated": 1}
		for code, amount in amounts.items()
	]


class TestBuildPnl(TestCase):
	def setUp(self) -> None:
		self.bookings = [
			booking("B1", kms=50, odenen=1300, bildirilen_odenen=1300),
			booking("B2", odenen=1500),
			booking("B3", statu="HOCA", ucret=0),
			booking("B4", iptal_edildi=1, odenen=200),
			booking("B5", tur="TUR-X"),
		]
		self.components = (
			comps("B1", HOTEL=300, FLIGHT=600)
			+ comps("B2", HOTEL=300, FLIGHT=600)
			+ comps("B3", HOTEL=300, FLIGHT=600)
			+ comps("B4", HOTEL=300, FLIGHT=600)
			+ comps("B5", HOTEL=999)
		)

	def pnl(self, **kwargs) -> dict:
		return build_pnl(
			tours=TOURS, bookings=self.bookings, components=self.components,
			tour_expenses={"TUR-A": 400}, overhead=kwargs.pop("overhead", 1000), **kwargs,
		)

	def test_tour_profit_formula(self) -> None:
		row = self.pnl()["tours"][0]
		self.assertEqual(row["tour"], "TUR-A")
		self.assertEqual(row["brut_satis"], 2600)
		self.assertEqual(row["komisyon"], 50)
		self.assertEqual(row["net_satis"], 2550)
		self.assertEqual(row["yolcu_maliyeti"], 2700)  # free HOCA passenger still costs
		self.assertEqual(row["tur_ekstra_gider"], 400)
		self.assertEqual(row["toplam_maliyet"], 3100)
		self.assertEqual(row["tur_kari"], -550)
		self.assertEqual(row["kisi_basi_kar"], -275)  # per paying passenger
		self.assertEqual(row["kisi_basi_maliyet"], round(3100 / 3, 2))

	def test_cancelled_booking_and_tour_are_excluded(self) -> None:
		result = self.pnl()
		self.assertEqual([r["tour"] for r in result["tours"]], ["TUR-A"])
		self.assertEqual(result["tours"][0]["kisi_sayisi"], 3)

	def test_season_result_subtracts_overhead(self) -> None:
		result = self.pnl()
		self.assertEqual(result["genel_gider"], 1000)
		self.assertEqual(result["sezon_sonucu"], -1550)
		self.assertIsNone(self.pnl(overhead=None)["sezon_sonucu"])

	def test_collections_do_not_net_across_passengers(self) -> None:
		row = self.pnl()["tours"][0]
		self.assertEqual(row["tahsil_edilen"], 2800)
		self.assertEqual(row["acik_alacak"], 0)
		self.assertEqual(row["fazla_odeme"], 250)  # B1 owed 1300 − 50 KMS, paid 1300
		self.assertEqual(row["excel_bildirilen"], 1300)

	def test_commission_reduces_receivable(self) -> None:
		self.bookings = [booking("B1", kms=50, odenen=1000), booking("B2", odenen=1300)]
		row = self.pnl()["tours"][0]
		self.assertEqual(row["acik_alacak"], 250)  # 1300 − 50 − 1000
		self.assertEqual(row["fazla_odeme"], 0)

	def test_status_rows_sum_to_tour(self) -> None:
		row = self.pnl()["tours"][0]
		net = sum(s["net_etki"] for s in row["by_status"].values())
		self.assertEqual(round(net, 2), round(row["net_satis"] - row["yolcu_maliyeti"], 2))

	def test_totals_equal_sum_of_tours(self) -> None:
		result = self.pnl()
		self.assertEqual(result["totals"]["tur_kari"], sum(r["tur_kari"] for r in result["tours"]))
		self.assertEqual(result["totals"]["maliyet_by_type"], {"FLIGHT": 1800, "HOTEL": 900})

	def test_non_usd_component_is_excluded_and_warned(self) -> None:
		self.components.append({"booking": "B1", "cost_type": "MANUAL", "currency": "SAR", "amount": 375, "is_system_generated": 0})
		result = self.pnl()
		self.assertEqual(result["tours"][0]["yolcu_maliyeti"], 2700)
		self.assertEqual(result["warnings"][0]["code"], "NON_USD_COMPONENT")

	def test_rule_checks_report_missing_and_stale(self) -> None:
		ctx = TourCostContext(tour="TUR-A", hotel_rule_count=1, hotel_per_person={1: 600, 2: 300, 3: 200, 4: 150})
		ctx.airfare = {"Normal": 650}
		ctx.visa = {"Umre": 0}
		ctx.diyanet = 40
		result = self.pnl(contexts={"TUR-A": ctx})
		codes = {w["code"]: w for w in result["warnings"]}
		self.assertEqual(codes["STALE"]["count"], 3)
		self.assertEqual(codes["ZERO_RULE"]["details"], {"VISA (Umre)": 3})
