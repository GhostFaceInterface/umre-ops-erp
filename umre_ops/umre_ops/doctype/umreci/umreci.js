// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

frappe.ui.form.on("Umreci", {
	async refresh(frm) {
		const $wrapper = frm.get_field("tur_gecmisi_html").$wrapper;
		if (frm.is_new()) {
			$wrapper.html(`<div class="text-muted">${__("Tur geçmişi kayıt sonrasında görüntülenir.")}</div>`);
			return;
		}
		$wrapper.html(`<div class="text-muted">${__("Tur geçmişi yükleniyor...")}</div>`);
		const response = await frappe.call({
			method: "umre_ops.umre_ops.doctype.umreci.umreci.get_tour_history",
			args: { umreci: frm.doc.name },
		});
		render_tour_history($wrapper, response.message || []);
	},
});

function render_tour_history($wrapper, rows) {
	const esc = frappe.utils.escape_html;
	const html = rows.map((row) => `
		<tr>
			<td><a href="/app/umre-tour/${encodeURIComponent(row.tur)}">${esc(row.tur_adi || row.tur)}</a></td>
			<td>${frappe.datetime.str_to_user(row.baslangic_tarihi || "") || "-"}</td>
			<td>${frappe.datetime.str_to_user(row.bitis_tarihi || "") || "-"}</td>
			<td>${esc(row.statu || "-")}</td><td>${esc(row.oda_tipi || "-")}</td>
			<td>${format_currency(row.ucret || 0, row.para_birimi || "USD")}</td>
			<td>${format_currency(row.odenen || 0, row.para_birimi || "USD")}</td>
			<td>${format_currency(row.bakiye || 0, row.para_birimi || "USD")}</td>
			<td><a href="/app/umre-booking/${encodeURIComponent(row.booking)}">${__("Rezervasyon")}</a></td>
		</tr>`).join("");
	$wrapper.html(`<div style="overflow:auto"><table class="table table-bordered table-hover">
		<thead><tr><th>${__("Tur")}</th><th>${__("Başlangıç")}</th><th>${__("Bitiş")}</th><th>${__("Statü")}</th><th>${__("Oda")}</th><th>${__("Ücret")}</th><th>${__("Ödenen")}</th><th>${__("Bakiye")}</th><th>${__("Detay")}</th></tr></thead>
		<tbody>${html || `<tr><td colspan="9" class="text-muted text-center">${__("Tur geçmişi yok.")}</td></tr>`}</tbody>
	</table></div>`);
}
