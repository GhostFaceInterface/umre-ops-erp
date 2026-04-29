frappe.pages["genel-gider-listesi"].on_page_load = function (wrapper) {
	new GenelGiderListesi(wrapper);
};

class GenelGiderListesi {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Genel Gider Listesi"),
			single_column: true
		});
		this.active_season = null;
		this.selected_season = null;
		this.seasons = [];
		this.entries = [];
		this.status_counts = {};
		this.make();
	}

	make() {
		this.container = $("<div>").css({
			maxWidth: "1200px",
			margin: "0 auto",
			padding: "20px"
		});
		this.page.main.empty().append(this.container);
		this.page.set_primary_action(__("Yeni Gider Girişi"), () => {
			frappe.set_route("genel-gider-girisi");
		});
		this.render_loading();
		this.load_context();
	}

	load_context() {
		Promise.all([
			frappe.call({
				method: "umre_ops.umre_ops.services.expense_service.get_active_season"
			}),
			frappe.call({
				method: "umre_ops.umre_ops.services.expense_service.get_seasons"
			})
		]).then(([active_response, seasons_response]) => {
			this.active_season = active_response.message || null;
			this.selected_season = this.active_season;
			this.seasons = seasons_response.message || [];
			this.load_entries();
		}).catch((err) => {
			console.error("Expense list context load failed", err);
			this.render_error(__("Gider listesi için sezon bilgisi yüklenemedi."));
		});
	}

	load_entries() {
		const filters = {};
		if (this.selected_season) {
			filters.season = this.selected_season;
		}
		this.render_loading();
		frappe.call({
			method: "umre_ops.umre_ops.services.expense_service.get_operational_expense_entries",
			args: { filters }
		}).then((response) => {
			const data = response.message || {};
			this.entries = data.entries || [];
			this.status_counts = data.status_counts || {};
			if (!this.selected_season) {
				this.selected_season = data.active_season || this.active_season;
			}
			this.render();
		}).catch((err) => {
			console.error("Operational expense entries load failed", err);
			this.render_error(__("Gider kayıtları yüklenemedi."));
		});
	}

	render_loading() {
		this.container.html(`<div class="text-muted">${__("Yükleniyor...")}</div>`);
	}

	render_error(message) {
		this.container.html(`<div class="frappe-card p-4 text-muted">${frappe.utils.escape_html(message)}</div>`);
	}

	render() {
		if (!this.selected_season) {
			this.render_error(__("Umre Ops Ayarları içinde Aktif Sezon seçilmeden gider listesi görüntülenemez."));
			return;
		}

		const total_confirmed = this.entries
			.filter((row) => row.status === "Confirmed")
			.reduce((sum, row) => sum + Number(row.usd_amount || 0), 0);

		this.container.html(`
			<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:16px;">
				<div>
					<div class="text-muted text-uppercase small">${__("Aktif Sezon")}</div>
					<div class="h4 mb-1">${frappe.utils.escape_html(this.active_season || this.selected_season)}</div>
					<div class="text-muted small">${__("Dashboard yalnızca Onaylandı durumundaki giderleri toplar.")}</div>
				</div>
				<div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
					<div style="min-width:260px;">
						<label class="text-muted text-uppercase small" for="umre-expense-list-season" style="display:block;margin-bottom:4px;">${__("Liste Sezonu")}</label>
						<select id="umre-expense-list-season" class="form-control" style="height:34px;border-color:#cfd4dc;">
							${this.render_season_options()}
						</select>
					</div>
					<button type="button" class="btn btn-default" id="umre-expense-list-refresh" style="height:34px;">${__("Yenile")}</button>
				</div>
			</div>

			<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px;">
				${this.render_summary_card(__("Onaylı Toplam"), this.format_money(total_confirmed, "USD"), "var(--blue-500)")}
				${this.render_summary_card(__("Onaylandı"), this.status_counts.Confirmed || 0, "var(--green-500)")}
				${this.render_summary_card(__("Taslak"), this.status_counts.Draft || 0, "var(--orange-500)")}
				${this.render_summary_card(__("İptal"), this.status_counts.Cancelled || 0, "var(--gray-500)")}
			</div>

			<div class="frappe-card p-0" style="border:1px solid #d5dae1;box-shadow:0 1px 2px rgba(15,23,42,0.04);overflow:hidden;">
				${this.render_entries()}
			</div>
		`);
		this.bind_actions();
	}

	render_summary_card(label, value, color) {
		return `
			<div class="frappe-card p-3" style="border:1px solid #d5dae1;border-left:4px solid ${color};box-shadow:0 1px 2px rgba(15,23,42,0.04);">
				<div class="text-muted text-uppercase small">${frappe.utils.escape_html(label)}</div>
				<div class="h4 mb-0">${frappe.utils.escape_html(String(value))}</div>
			</div>
		`;
	}

	render_entries() {
		if (!this.entries.length) {
			return `<div class="p-4 text-muted">${__("Bu sezon için genel gider kaydı bulunmuyor.")}</div>`;
		}

		return `
			<div style="overflow-x:auto;">
				<table class="table table-bordered m-0">
					<thead>
						<tr>
							<th>${__("Tarih")}</th>
							<th>${__("Durum")}</th>
							<th>${__("Ana Başlık")}</th>
							<th>${__("Gider Kalemi")}</th>
							<th>${__("Açıklama")}</th>
							<th class="text-right">${__("Tutar")}</th>
							<th class="text-right">${__("USD")}</th>
							<th>${__("Dekont")}</th>
						</tr>
					</thead>
					<tbody>
						${this.entries.map((row) => this.render_entry_row(row)).join("")}
					</tbody>
				</table>
			</div>
		`;
	}

	render_entry_row(row) {
		const attachment = row.receipt_attachment
			? `<a href="${frappe.utils.escape_html(row.receipt_attachment)}" target="_blank" rel="noopener">${__("Aç")}</a>`
			: `<span class="text-muted">-</span>`;
		return `
			<tr data-expense-name="${frappe.utils.escape_html(row.name || "")}" style="cursor:pointer;">
				<td style="white-space:nowrap;">${frappe.utils.escape_html(this.format_date(row.expense_date))}</td>
				<td>${this.render_status(row.status)}</td>
				<td>${frappe.utils.escape_html(row.main_category_label || "")}</td>
				<td>
					<div>${frappe.utils.escape_html(row.category_label || "")}</div>
					<div class="text-muted small">${frappe.utils.escape_html(row.paid_to || row.money_account || "")}</div>
				</td>
				<td style="max-width:280px;">${frappe.utils.escape_html(row.description || "")}</td>
				<td class="text-right" style="white-space:nowrap;">${this.format_money(row.amount, row.currency)}</td>
				<td class="text-right" style="white-space:nowrap;font-weight:600;">${this.format_money(row.usd_amount, "USD")}</td>
				<td>${attachment}</td>
			</tr>
		`;
	}

	render_status(status) {
		const normalized = status || "Draft";
		const label = normalized === "Confirmed" ? __("Onaylandı") : normalized === "Cancelled" ? __("İptal") : __("Taslak");
		const color = normalized === "Confirmed" ? "green" : normalized === "Cancelled" ? "gray" : "orange";
		const note = normalized === "Draft" ? `<div class="text-muted small">${__("Dashboard'a dahil değil")}</div>` : "";
		return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(label)}</span>${note}`;
	}

	render_season_options() {
		const seen = new Set();
		const rows = [];
		(this.seasons || []).forEach((season) => {
			if (!season.name || seen.has(season.name)) return;
			seen.add(season.name);
			rows.push(season);
		});
		if (this.selected_season && !seen.has(this.selected_season)) {
			rows.unshift({ name: this.selected_season, season_name: this.selected_season });
		}
		return rows.map((season) => {
			const name = season.name || "";
			const label = season.season_name || season.name || "";
			const selected = name === this.selected_season ? "selected" : "";
			return `<option value="${frappe.utils.escape_html(name)}" ${selected}>${frappe.utils.escape_html(label)}</option>`;
		}).join("");
	}

	bind_actions() {
		this.container.find("#umre-expense-list-season").on("change", (event) => {
			this.selected_season = $(event.currentTarget).val() || this.active_season;
			this.load_entries();
		});
		this.container.find("#umre-expense-list-refresh").on("click", () => {
			this.load_entries();
		});
		this.container.find("tr[data-expense-name]").on("click", (event) => {
			if ($(event.target).closest("a").length) return;
			const name = $(event.currentTarget).attr("data-expense-name");
			if (name) {
				frappe.set_route("Form", "Operational Expense", name);
			}
		});
	}

	format_date(value) {
		if (!value) return "-";
		if (frappe.datetime && frappe.datetime.str_to_user) {
			return frappe.datetime.str_to_user(value);
		}
		return value;
	}

	format_money(value, currency) {
		const amount = Number(value || 0);
		const cur = (currency || "USD").toString().toUpperCase();
		try {
			return new Intl.NumberFormat("en-US", { style: "currency", currency: cur }).format(amount);
		} catch (e) {
			return cur + " " + amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
		}
	}
}
