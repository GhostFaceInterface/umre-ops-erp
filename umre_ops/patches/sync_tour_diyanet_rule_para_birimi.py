# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Retired data fix.

It used to align `Tour Diyanet Card Rule.para_birimi` with the tour currency.
Every cost rule now forces USD on validate (`tour_diyanet_card_rule.py`) and
`normalize_cost_rule_usd_contract` enforces the USD contract, so there is
nothing left to align. Kept as a no-op because it is listed in patches.txt.
"""
from __future__ import annotations


def execute() -> None:
	return None
