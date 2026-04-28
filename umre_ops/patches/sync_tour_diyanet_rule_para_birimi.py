# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Data fix: `Tour Diyanet Card Rule` defaults `para_birimi` to USD. When the
linked `Umre Tour` uses a different currency, the cost engine refuses to
emit DIYANET (single-currency per booking) and the tour recompute can fail
or leave stale component rows. Align rule currency to the tour, then
operators should run a full recompute (``recompute_tour_bookings`` / desk).
"""
from __future__ import annotations

import frappe

from umre_ops.umre_ops.services.cost_engine import sync_tour_diyanet_rule_currencies_from_tour


def execute() -> None:
	# No inline commit: migration run commits the patch transaction
	out = sync_tour_diyanet_rule_currencies_from_tour(commit=False)
	print(f"[sync_tour_diyanet_rule_para_birimi] {out!r}")
