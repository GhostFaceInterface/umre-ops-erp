// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

const TOUR_API = "umre_ops.umre_ops.doctype.umre_tour.umre_tour";

frappe.ui.form.on("Umre Tour", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.get_field("tur_detayi_html").$wrapper.html(
				`<div class="text-muted">${__("Tur detayını görmek için önce turu kaydedin.")}</div>`,
			);
			return;
		}
		load_tour_roster(frm);
	},
});

async function load_tour_roster(frm) {
	const $wrapper = frm.get_field("tur_detayi_html").$wrapper;
	$wrapper.html(`<div class="text-muted">${__("Katılımcılar yükleniyor...")}</div>`);
	try {
		const response = await frappe.call({ method: `${TOUR_API}.get_tour_participants`, args: { tour: frm.doc.name } });
		render_tour_roster(frm, response.message || {}, $wrapper);
	} catch (error) {
		$wrapper.html(`<div class="text-danger">${__("Tur detayı yüklenemedi.")}</div>`);
		throw error;
	}
}

function render_tour_roster(frm, data, $wrapper) {
	const esc = frappe.utils.escape_html;
	const rows = data.participants || [];
	const money = (value) => format_currency(value || 0, data.currency || "USD");
	const row_html = rows.map((row) => `
		<tr data-booking="${esc(row.booking)}">
			<td><a href="/app/umreci/${encodeURIComponent(row.umreci)}">${esc(`${row.ad || ""} ${row.soyad || ""}`.trim())}</a><br><small>${esc(row.masked_identity || "")}</small></td>
			<td>${esc(row.telefon_numarasi || "-")}</td><td>${esc(row.statu || "-")}</td>
			<td>${esc(row.oda_tipi || "-")}</td>
			<td>${esc([row.ic_hat_baglanti, row.arrival_city, row.return_city].filter(Boolean).join(" → ") || "-")}</td>
			<td>${esc(row.kimden_geldi || "-")}</td><td>${money(row.ucret)}</td><td>${money(row.odenen)}</td><td>${money(row.bakiye)}</td>
			<td><a href="/app/umre-booking/${encodeURIComponent(row.booking)}">${__("Detay")}</a></td>
		</tr>`).join("");

	$wrapper.html(`
		<div class="tour-roster-toolbar" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
			<input class="form-control tour-roster-search" style="max-width:300px" placeholder="${__("İsim, telefon veya statü ara")}">
			<span class="text-muted">${__("{0} kişi · Ücret {1} · Ödenen {2}", [data.count || 0, money(data.total_ucret), money(data.total_odenen)])}</span>
		</div>
		<div style="overflow:auto"><table class="table table-bordered table-hover tour-roster-table">
			<thead><tr><th>${__("Umreci")}</th><th>${__("Telefon")}</th><th>${__("Statü")}</th><th>${__("Oda")}</th><th>${__("Şehirler")}</th><th>${__("Referans")}</th><th>${__("Ücret")}</th><th>${__("Ödenen")}</th><th>${__("Bakiye")}</th><th>${__("İşlem")}</th></tr></thead>
			<tbody>${row_html || `<tr><td colspan="10" class="text-muted text-center">${__("Bu turda katılımcı yok.")}</td></tr>`}</tbody>
		</table></div>`);

	$wrapper.off(".umreTour");
	$wrapper.on("input.umreTour", ".tour-roster-search", function () {
		const needle = String($(this).val() || "").toLocaleLowerCase("tr");
		$wrapper.find("tbody tr[data-booking]").each(function () {
			$(this).toggle($(this).text().toLocaleLowerCase("tr").includes(needle));
		});
	});
}
