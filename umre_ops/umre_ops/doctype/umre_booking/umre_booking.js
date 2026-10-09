// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

// Optional UX: debounced preview. Source of truth: services/cost_engine.py
// (the same function computes the preview and the persisted cost components).
// Disable any Desk "Client Script" for this DocType to avoid double handlers.

frappe.ui.form.on("Umre Booking", {
	refresh(frm) {
		frm.add_custom_button(__("Recalculate (preview)"), () => {
			run_booking_preview(frm);
		});
	},
});

const PREVIEW_FIELDS = [
	"statu",
	"manual_cost",
	"umreci",
	"tur",
	"oda_tipi",
	"yolcu_tipi",
	"vize_tipi",
	"ucret",
	"kms",
	"odenen",
	"iptal_edildi",
];

// Only derived (read-only) values are written back; inputs typed by the user
// are never overwritten by a preview response.
const DERIVED_FIELDS = [
	"otel_maliyeti",
	"ucak_maliyeti",
	"vize_maliyeti",
	"diyanet_maliyeti",
	"toplam_maliyet",
	"kar",
];

const ISSUE_LABELS = {
	MISSING_RULE: __("kural yok"),
	ZERO_RULE: __("kural tutarı 0"),
	INVALID_RATE: __("kur geçersiz"),
	MISSING_PASSENGER_TYPE: __("yolcu tipi boş"),
	MANUAL_COST_MISSING: __("manuel maliyet yok"),
};

let _preview_timer = null;
let _preview_seq = 0;

function run_booking_preview(frm) {
	const seq = ++_preview_seq;
	frm.call({
		method: "umre_ops.umre_ops.doctype.umre_booking.umre_booking.preview_calculated_fields",
		args: { doc: frm.doc },
		callback(r) {
			if (seq !== _preview_seq || !r.message) {
				return;
			}
			const msg = r.message;
			for (const fieldname of DERIVED_FIELDS) {
				if (fieldname in msg && frm.doc[fieldname] !== msg[fieldname]) {
					frm.doc[fieldname] = msg[fieldname];
				}
			}
			for (const fieldname of ["yolcu_tipi", "vize_tipi"]) {
				if (!frm.doc[fieldname] && msg[fieldname]) {
					frm.set_value(fieldname, msg[fieldname]);
				}
			}
			frm.refresh_fields(DERIVED_FIELDS);
			show_cost_issues(frm, msg.issues || []);
		},
	});
}

function show_cost_issues(frm, issues) {
	frm.dashboard.clear_headline();
	if (!issues.length) {
		return;
	}
	const text = issues
		.map((issue) => `${issue.cost_type}${issue.detail ? " (" + issue.detail + ")" : ""}: ${ISSUE_LABELS[issue.code] || issue.code}`)
		.join(" · ");
	frm.dashboard.set_headline_alert(
		`${__("Maliyet eksik")}: ${frappe.utils.escape_html(text)}`,
		"orange"
	);
}

function debounced_preview(frm) {
	if (_preview_timer) {
		clearTimeout(_preview_timer);
	}
	_preview_timer = setTimeout(() => run_booking_preview(frm), 400);
}

PREVIEW_FIELDS.forEach((fieldname) => {
	frappe.ui.form.on("Umre Booking", fieldname, (frm) => {
		debounced_preview(frm);
	});
});
