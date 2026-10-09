// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

frappe.query_reports["Tour Revenue Summary"] = {
	filters: [
		{
			fieldname: "season",
			label: __("Sezon"),
			fieldtype: "Link",
			options: "Umre Season",
			reqd: 1,
		},
		{
			fieldname: "tour",
			label: __("Tur"),
			fieldtype: "Link",
			options: "Umre Tour",
			get_query: () => {
				const season = frappe.query_report.get_filter_value("season");
				return season ? { filters: { season } } : {};
			},
		},
	],
	tree: true,
	name_field: "tour_key",
	parent_field: "parent_tour_key",
	initial_depth: 0,
	onload(report) {
		if (report.get_filter_value("season")) return;
		frappe
			.call("umre_ops.umre_ops.services.expense_service.get_active_season")
			.then((r) => r && r.message && report.set_filter_value("season", r.message));
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		const kind = data.row_kind;

		if (column.fieldname === "tour") {
			if (kind === "tour") return `<strong>${value}</strong>`;
			if (kind === "section") {
				return `<span style="color:#6c7079;font-weight:600;text-transform:uppercase;letter-spacing:0.6px;font-size:11px;">${value}</span>`;
			}
			return `<span style="color:#4f5660;">${value}</span>`;
		}

		const signed = { tur_kari: true, detay_tutar: kind === "status" };
		if (signed[column.fieldname] && data[column.fieldname] !== undefined && data[column.fieldname] !== "") {
			const num = parseFloat(data[column.fieldname]);
			if (!isNaN(num)) {
				const color = num > 0 ? "#1f8b4c" : num < 0 ? "#c0392b" : "#7f8c8d";
				return `<span style="color:${color};font-weight:${kind === "tour" ? 700 : 600};">${value}</span>`;
			}
		}
		if (kind === "tour" && ["net_satis", "toplam_maliyet"].includes(column.fieldname)) {
			return `<span style="font-weight:700;">${value}</span>`;
		}
		return value;
	},
};
