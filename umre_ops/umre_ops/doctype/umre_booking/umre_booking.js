// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

// Optional UX: debounced preview. Source of truth: validate() in umre_booking.py +
// services/booking_calculation_service.py. Disable any Desk "Client Script" for this
// DocType to avoid double handlers.

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
	"diyanet_kart_var",
	"odenen",
	"kms",
];

let _preview_timer = null;

function run_booking_preview(frm) {
	frm.call({
		method: "umre_ops.umre_ops.doctype.umre_booking.umre_booking.preview_calculated_fields",
		args: { doc: frm.doc },
		callback(r) {
			if (!r.message) {
				return;
			}
			for (const k of Object.keys(r.message)) {
				frm.set_value(k, r.message[k]);
			}
			frm.refresh_fields();
		},
	});
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
