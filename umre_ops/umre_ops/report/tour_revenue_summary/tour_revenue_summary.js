// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

frappe.query_reports["Tour Revenue Summary"] = {
	filters: [
		{
			fieldname: "tour",
			label: __("Tour"),
			fieldtype: "Link",
			options: "Umre Tour",
		},
	],
	tree: true,
	name_field: "tour_key",
	parent_field: "parent_tour_key",
	initial_depth: 0,
	formatter: function (value, row, column, data, default_formatter) {
		const kind = data && data.row_kind;

		const NUMERIC_FIELDS_BY_KIND = {
			section: new Set(["kisi_sayisi", "gelir", "tahsil_edilen", "kalan_alacak", "toplam_maliyet", "net_kar"]),
			status: new Set(["tahsil_edilen", "kalan_alacak"]),
			cost: new Set(["kisi_sayisi", "gelir", "tahsil_edilen", "kalan_alacak", "net_kar"]),
		};

		const hideSet = NUMERIC_FIELDS_BY_KIND[kind];
		if (hideSet && hideSet.has(column.fieldname)) {
			return "";
		}

		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === "tour") {
			if (kind === "tour") {
				value = `<strong>${value}</strong>`;
			} else if (kind === "section") {
				value = `<span style="color:#6c7079;font-weight:600;text-transform:uppercase;letter-spacing:0.6px;font-size:11px;">${value}</span>`;
			} else if (kind === "status") {
				value = `<span style="color:#1f272e;">${value}</span>`;
			} else if (kind === "cost") {
				value = `<span style="color:#4f5660;">${value}</span>`;
			}
		}

		if (column.fieldname === "net_kar" && data.net_kar !== null && data.net_kar !== undefined && data.net_kar !== "") {
			const num = parseFloat(data.net_kar);
			if (!isNaN(num)) {
				let color = "#7f8c8d";
				if (num > 0) color = "#1f8b4c";
				else if (num < 0) color = "#c0392b";
				const weight = kind === "tour" ? 700 : 600;
				value = `<span style="color:${color};font-weight:${weight};">${value}</span>`;
			}
		}

		if (column.fieldname === "toplam_maliyet" && data.toplam_maliyet) {
			const num = parseFloat(data.toplam_maliyet);
			if (!isNaN(num) && num > 0) {
				const weight = kind === "tour" ? 700 : 500;
				value = `<span style="color:#c0392b;font-weight:${weight};">${value}</span>`;
			}
		}

		if (column.fieldname === "gelir" && data.gelir) {
			const num = parseFloat(data.gelir);
			if (!isNaN(num) && num > 0 && kind === "tour") {
				value = `<span style="font-weight:700;">${value}</span>`;
			}
		}

		if (column.fieldname === "tahsil_edilen" && data.tahsil_edilen) {
			const num = parseFloat(data.tahsil_edilen);
			if (!isNaN(num) && num > 0 && kind === "tour") {
				value = `<span style="color:#1f8b4c;font-weight:700;">${value}</span>`;
			}
		}

		if (column.fieldname === "kalan_alacak" && data.kalan_alacak) {
			const num = parseFloat(data.kalan_alacak);
			if (!isNaN(num) && num > 0 && kind === "tour") {
				value = `<span style="color:#b9770e;font-weight:600;">${value}</span>`;
			}
		}

		return value;
	},
};
