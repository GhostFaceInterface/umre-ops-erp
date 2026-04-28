# Copyright (c) 2026, Sermed Turizm
# Merges legacy `bir_kisilik_oda_maliyeti` into canonical `bir_kisilik_oda_maaliyeti` and drops duplicate.
import frappe


def execute():
    t = "`tabTour Hotel Cost Rule`"

    def col(name: str) -> bool:
        return bool(
            frappe.db.sql(
                """
				SELECT COUNT(*) FROM information_schema.COLUMNS
				WHERE TABLE_SCHEMA = DATABASE()
				  AND TABLE_NAME = 'tabTour Hotel Cost Rule'
				  AND BINARY COLUMN_NAME = %s
				""",
                (name,),
            )[0][0]
        )

    if not (col("bir_kisilik_oda_maliyeti") and col("bir_kisilik_oda_maaliyeti")):
        return

    frappe.db.sql(
        f"""
		UPDATE {t} SET `bir_kisilik_oda_maaliyeti` = COALESCE(
			NULLIF(`bir_kisilik_oda_maaliyeti`, 0),
			`bir_kisilik_oda_maliyeti`,
			0
		)
		"""
    )
    frappe.db.sql_ddl(f"ALTER TABLE {t} DROP COLUMN `bir_kisilik_oda_maliyeti`")
