# Copyright (c) 2026, Sermed Turizm
# Pre-model-sync patch: physical MariaDB columns -> ASCII canonical fieldnames
# Run once before Frappe re-syncs DocType from JSON. Logged; reversible via site backup.
import json
from datetime import datetime

import frappe


def _log(msg, data=None):
    entry = {
        "time": datetime.utcnow().isoformat() + "Z",
        "message": msg,
        "data": data,
    }
    frappe.log_error(
        message=json.dumps(entry, ensure_ascii=False, default=str),
        title="umre_ops reconcile_schema",
    )


def _db_name():
    return frappe.local.conf.get("db_name") or getattr(frappe.db, "cur_db_name", None)


def _col_exists(db, table, column) -> bool:
    r = frappe.db.sql(
        """
		SELECT COUNT(*)
		FROM information_schema.COLUMNS
		WHERE TABLE_SCHEMA = %s
		  AND BINARY TABLE_NAME = BINARY %s
		  AND BINARY COLUMN_NAME = BINARY %s
		""",
        (db, table, column),
    )
    return bool(r and r[0][0])


def _run(sql, *args, **kwargs):
    frappe.db.sql(sql, *args, **kwargs)


def _ddl(sql, debug=False):
    """Use for ALTER/DROP/CHANGE — avoids ImplicitCommitError in patch context."""
    frappe.db.sql_ddl(sql, debug=debug)


def _has_table(tablename: str) -> bool:
    return bool(frappe.db.sql("SHOW TABLES LIKE %s", (tablename,)))


def execute():
    """
    Reconcile `umre_ops` business tables. Idempotent: skips renames if already applied.
    """
    db = _db_name()
    _log("umre_ops reconcile_schema start", {"database": db})

    # ------------------------------------------------------------------
    # tabUmre Tour
    # ------------------------------------------------------------------
    t_tour = "tabUmre Tour"
    if _has_table(t_tour):
        # 1) Merge all legacy start-date columns into `baslangic_tarihi` (canonical ASCII)
        if all(
            _col_exists(db, t_tour, c)
            for c in (
                "baslangic_tarihi",
                "başlangıç_tarihi",
                "başlangic_tarihi",
            )
        ):
            _run(
                f"""
				UPDATE `{t_tour}` SET
					`baslangic_tarihi` = COALESCE(
						`baslangic_tarihi`,
						`başlangic_tarihi`,
						`başlangıç_tarihi`
					)
				"""
            )
            _log("merged start date columns into baslangic_tarihi", {})
        elif _col_exists(db, t_tour, "baslangic_tarihi"):
            # if only a subset of legacy columns exist, merge in two steps
            for c in ("başlangic_tarihi", "başlangıç_tarihi"):
                if _col_exists(db, t_tour, c):
                    _run(
                        f"""
						UPDATE `{t_tour}` SET `baslangic_tarihi` = COALESCE(`baslangic_tarihi`, `{c}`)
						WHERE `baslangic_tarihi` IS NULL
						"""
                    )
        # 2) tur_adı (UNI) -> tur_adi: drop index first if present
        if _col_exists(db, t_tour, "tur_adı") and not _col_exists(db, t_tour, "tur_adi"):
            idx = frappe.db.sql(
                f"SHOW INDEX FROM `{t_tour}` WHERE Key_name = 'tur_adı'"
            )
            if idx:
                _ddl(f"ALTER TABLE `{t_tour}` DROP INDEX `tur_adı`")
            _ddl(
                f"ALTER TABLE `{t_tour}` CHANGE COLUMN `tur_adı` `tur_adi` varchar(140) NULL"
            )
            _ddl(f"ALTER TABLE `{t_tour}` ADD UNIQUE KEY `tur_adi` (`tur_adi`)")
            _log("renamed column", {"old": "tur_adı", "new": "tur_adi"})
        # 3) bitiş_tarihi -> bitis_tarihi
        if _col_exists(db, t_tour, "bitiş_tarihi") and not _col_exists(
            db, t_tour, "bitis_tarihi"
        ):
            _ddl(
                f"ALTER TABLE `{t_tour}` CHANGE COLUMN `bitiş_tarihi` `bitis_tarihi` date NULL"
            )
            _log("renamed column", {"old": "bitiş_tarihi", "new": "bitis_tarihi"})
        # 4) coalesce into bir_kisilik_oda / dort_kisilik_oda from typo / legacy
        bcols = [c for c in ("bir_kisilik_oda", "bir_kişilik_oda", "1_kişilik_oda") if _col_exists(db, t_tour, c)]
        if bcols and _col_exists(db, t_tour, "bir_kisilik_oda"):
            parts = ", ".join(f"NULLIF(`{c}`, 0)" for c in bcols)
            _run(f"UPDATE `{t_tour}` SET `bir_kisilik_oda` = COALESCE({parts}, 0)")
            _log("merged 1-occupant room price variants", {"columns": bcols})
        if _col_exists(db, t_tour, "dort_kisilik_oda") and _col_exists(
            db, t_tour, "dort_disilik_oda"
        ):
            _run(
                f"""
				UPDATE `{t_tour}` SET `dort_kisilik_oda` = COALESCE(
					NULLIF(`dort_kisilik_oda`, 0),
					NULLIF(`dort_disilik_oda`, 0),
					0
				)
				"""
            )
        # 5) drop obsolete physical columns
        to_drop = [
            "1_kişilik_oda",
            "bir_kişilik_oda",
            "başlangıç_tarihi",
            "başlangic_tarihi",
            "dort_disilik_oda",
            "uçak_maaliyeti",
            "otel_maaliyeti",
            "vize_maaliyeti",
        ]
        for col in to_drop:
            if _col_exists(db, t_tour, col):
                _ddl(f"ALTER TABLE `{t_tour}` DROP COLUMN `{col}`")
                _log("dropped column", {"table": t_tour, "column": col})

    # ------------------------------------------------------------------
    # tabUmreci
    # ------------------------------------------------------------------
    t_u = "tabUmreci"
    if _has_table(t_u):
        if _col_exists(db, t_u, "doğum_tarihi") and _col_exists(db, t_u, "dogum_tarihi"):
            _run(
                f"UPDATE `{t_u}` SET `dogum_tarihi` = COALESCE(`dogum_tarihi`, `doğum_tarihi`)"
            )
            _log("merged doğum_tarihi into dogum_tarihi", {})
        if _col_exists(db, t_u, "doğum_tarihi"):
            _ddl(f"ALTER TABLE `{t_u}` DROP COLUMN `doğum_tarihi`")
            _log("dropped column", {"table": t_u, "column": "doğum_tarihi"})
        if _col_exists(db, t_u, "telefon_numarası") and not _col_exists(
            db, t_u, "telefon_numarasi"
        ):
            _ddl(
                f"ALTER TABLE `{t_u}` CHANGE COLUMN `telefon_numarası` `telefon_numarasi` varchar(140) NULL"
            )
            _log("renamed column", {"old": "telefon_numarası", "new": "telefon_numarasi"})

    # ------------------------------------------------------------------
    # tabUmre Booking — diyanet_karti_var duplicate
    # ------------------------------------------------------------------
    t_b = "tabUmre Booking"
    if _has_table(t_b):
        if _col_exists(db, t_b, "diyanet_karti_var") and _col_exists(
            db, t_b, "diyanet_kart_var"
        ):
            _run(
                f"""
				UPDATE `{t_b}` SET
					`diyanet_kart_var` = GREATEST(
						IFNULL(`diyanet_kart_var`, 0), IFNULL(`diyanet_karti_var`, 0)
					)
				"""
            )
            _ddl(f"ALTER TABLE `{t_b}` DROP COLUMN `diyanet_karti_var`")
            _log("merged diyanet_karti_var into diyanet_kart_var and dropped", {})

    # ------------------------------------------------------------------
    # tabTour Passenger Cost Rule
    # ------------------------------------------------------------------
    t_p = "tabTour Passenger Cost Rule"
    if _has_table(t_p):
        if _col_exists(db, t_p, "maliyet_tipi") and not _col_exists(
            db, t_p, "expense_component"
        ):
            _ddl(
                f"ALTER TABLE `{t_p}` CHANGE COLUMN `maliyet_tipi` `expense_component` varchar(140) NULL"
            )
            _log("renamed maliyet_tipi -> expense_component", {})
        for col in ("vize_tipi", "maliyet_kalemleri"):
            if _col_exists(db, t_p, col):
                _ddl(f"ALTER TABLE `{t_p}` DROP COLUMN `{col}`")
                _log("dropped orphan", {"table": t_p, "column": col})

    # ------------------------------------------------------------------
    # tabTour Visa Cost Rule
    # ------------------------------------------------------------------
    t_v = "tabTour Visa Cost Rule"
    if _has_table(t_v):
        if _col_exists(db, t_v, "kural_kodu"):
            _ddl(f"ALTER TABLE `{t_v}` DROP COLUMN `kural_kodu`")
            _log("dropped kural_kodu (empty legacy)", {"table": t_v})

    frappe.db.commit()
    _log("umre_ops reconcile_schema done", {"status": "ok"})
