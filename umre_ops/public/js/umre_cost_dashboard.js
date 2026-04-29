/*
 * Umre Operasyon Paneli — Financial Dashboard
 *
 * Strategy: detect when the user lands on the "Umre Operasyon Paneli"
 * Workspace, mount our financial panel above the existing link cards,
 * and refetch on `umre_cost_dashboard_dirty` realtime events.
 *
 * Single source of truth: backend `umre_ops.umre_ops.services.dashboard_service.get_tour_cost_breakdown`.
 */
(function () {
	"use strict";

	const PANEL_ID = "umre-fin-panel";
	const WORKSPACE_NAME = "Umre Operasyon Paneli";
	const WORKSPACE_ROUTES = ["umre-operasyon-paneli", "Umre Operasyon Paneli"];
	const ENDPOINT = "umre_ops.umre_ops.services.dashboard_service.get_tour_cost_breakdown";
	const COST_COLORS = ["#ff4d4f", "#ff7a45", "#ffa940", "#36cfc9", "#597ef7", "#9254de", "#13c2c2"];

	let _state = {
		tour: "",        // "" = all tours
		loading: false,
		debounce_handle: null,
		chart: null,
		last_payload: null
	};

	function fmt_money(value, currency) {
		const n = Number(value || 0);
		const cur = (currency || "USD").toString().toUpperCase();
		// Force ISO USD formatting so we never show wrong symbols (e.g. "L") from
		// corrupted Currency master rows or Company TRY defaults bleeding into Desk.
		if (cur === "USD") {
			try {
				return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
			} catch (e) {
				/* fall through */
			}
		}
		if (typeof format_currency === "function") {
			try {
				return format_currency(n, cur);
			} catch (e) {
				/* fall through */
			}
		}
		try {
			return frappe.format(n, { fieldtype: "Currency", options: cur });
		} catch (e) {
			return cur + " " + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
		}
	}

	function fmt_pct(value) {
		const n = Number(value || 0) * 100;
		return n.toFixed(1) + "%";
	}

	function fmt_pct_value(value) {
		return Number(value || 0).toFixed(1) + "%";
	}

	function fmt_int(value) {
		return Number(value || 0).toLocaleString("tr-TR");
	}

	const SEASON_PANEL_ID = "umre-season-fin-panel";
	const SEASON_ENDPOINT = "umre_ops.umre_ops.services.dashboard_service.get_operational_dashboard_data";

	let _season_state = {
		chart_cat: null,
		chart_month: null
	};

	function on_target_route() {
		const route = (frappe.get_route && frappe.get_route()) || [];
		if (!route || !route.length) return false;
		if (route[0] === "Workspaces" && WORKSPACE_ROUTES.includes(route[1])) return true;
		return WORKSPACE_ROUTES.includes(route[0]) || route.join("/").includes("umre-operasyon-paneli");
	}

	function ensure_mounted() {
		if (!on_target_route()) {
			const tp = document.getElementById(PANEL_ID);
			if (tp) tp.remove();
			const sp = document.getElementById(SEASON_PANEL_ID);
			if (sp) sp.remove();
			_state.chart = null;
			_season_state.chart_cat = null;
			_season_state.chart_month = null;
			return;
		}

		const candidates = [
			document.querySelector(".workspace-sidebar-toggle ~ .codex-editor"),
			document.querySelector(".layout-main-section .codex-editor"),
			document.querySelector(".codex-editor")
		];
		const container = candidates.find(Boolean);
		if (!container) return;

		if (!document.getElementById(PANEL_ID)) {
			const panel = document.createElement("div");
			panel.id = PANEL_ID;
			panel.className = "umre-fin-panel";
			panel.innerHTML = render_skeleton();
			container.parentNode.insertBefore(panel, container);
			wire_events(panel);
			schedule_refresh(0);
		}

		ensure_season_panel();
	}

	function ensure_season_panel() {
		const tour = document.getElementById(PANEL_ID);
		if (!tour || document.getElementById(SEASON_PANEL_ID)) return;
		const sp = document.createElement("div");
		sp.id = SEASON_PANEL_ID;
		sp.className = "umre-fin-panel umre-season-fin-panel";
		sp.innerHTML = render_season_skeleton();
		tour.after(sp);
		wire_season_events(sp);
		schedule_season_refresh(0);
	}

	function render_skeleton() {
		return `
			<div class="umre-fin-panel__header">
				<div class="umre-fin-panel__title"><span class="dot"></span>${__("Tur Maliyeti Paneli")}</div>
				<div class="umre-fin-panel__filter">
					<label for="umre-fin-tour">${__("Tur")}</label>
					<select id="umre-fin-tour"><option value="">${__("Tüm Turlar")}</option></select>
					<button type="button" class="umre-fin-panel__refresh" id="umre-fin-refresh">${__("Yenile")}</button>
				</div>
			</div>
			<div class="umre-fin-hero" id="umre-fin-hero"></div>

			<div class="umre-fin-section">
				<div class="umre-fin-section__title">${__("Maliyet Dağılımı")}</div>
				<div class="umre-fin-section__rule"></div>
			</div>
			<div class="umre-fin-cost">
				<div class="umre-fin-cost__cards" id="umre-fin-cards"></div>
				<div class="umre-fin-cost__chart">
					<div class="umre-fin-cost__chart-title">${__("Maliyet Dağılımı (%)")}</div>
					<div class="umre-fin-cost__chart-body" id="umre-fin-chart"></div>
				</div>
			</div>

			<div class="umre-fin-section">
				<div class="umre-fin-section__title">${__("Performans")}</div>
				<div class="umre-fin-section__rule"></div>
			</div>
			<div class="umre-fin-kpi" id="umre-fin-kpi"></div>
		`;
	}

	function wire_events(panel) {
		const sel = panel.querySelector("#umre-fin-tour");
		sel.addEventListener("change", function () {
			_state.tour = sel.value || "";
			schedule_refresh(0);
		});
		const btn = panel.querySelector("#umre-fin-refresh");
		btn.addEventListener("click", function () {
			btn.classList.remove("is-stale");
			schedule_refresh(0);
		});
	}

	function schedule_refresh(delay_ms) {
		if (_state.debounce_handle) clearTimeout(_state.debounce_handle);
		_state.debounce_handle = setTimeout(refresh, delay_ms == null ? 250 : delay_ms);
	}

	function render_season_skeleton() {
		return `
			<div class="umre-fin-panel__header">
				<div class="umre-fin-panel__title umre-season-fin-panel__title"><span class="dot"></span>${__("Sezonluk Genel Giderler")}</div>
				<div class="umre-fin-panel__filter umre-season-filters">
					<button type="button" class="umre-fin-panel__refresh" id="umre-season-refresh">${__("Yenile")}</button>
				</div>
			</div>
			<div class="umre-fin-hero umre-season-hero" id="umre-season-total"></div>
			<div class="umre-fin-section">
				<div class="umre-fin-section__title">${__("Kategori Kartları")}</div>
				<div class="umre-fin-section__rule"></div>
			</div>
			<div class="umre-fin-cost__cards" id="umre-season-cards"></div>
			<div class="umre-fin-section">
				<div class="umre-fin-section__title">${__("Gider Kalemleri")}</div>
				<div class="umre-fin-section__rule"></div>
			</div>
			<div id="umre-season-items"></div>
			<div class="umre-fin-section">
				<div class="umre-fin-section__title">${__("Genel Gider Grafikleri")}</div>
				<div class="umre-fin-section__rule"></div>
			</div>
			<div class="umre-fin-cost umre-season-charts">
				<div class="umre-fin-cost__chart">
					<div class="umre-fin-cost__chart-title">${__("Kategori Dağılımı (USD)")}</div>
					<div class="umre-fin-cost__chart-body" id="umre-season-chart-cat"></div>
				</div>
				<div class="umre-fin-cost__chart">
					<div class="umre-fin-cost__chart-title">${__("Aylık Trend")}</div>
					<div class="umre-fin-cost__chart-body" id="umre-season-chart-month"></div>
				</div>
			</div>`;
	}

	function wire_season_events(sp) {
		sp.querySelector("#umre-season-refresh").addEventListener("click", function () {
			schedule_season_refresh(0);
		});
	}

	let _season_debounce = null;
	function schedule_season_refresh(ms) {
		if (_season_debounce) clearTimeout(_season_debounce);
		_season_debounce = setTimeout(refresh_season, ms == null ? 200 : ms);
	}

	function refresh_season() {
		const sp = document.getElementById(SEASON_PANEL_ID);
		if (!sp) return;
		sp.classList.add("umre-fin-loading");
		frappe.call({
			method: SEASON_ENDPOINT,
			args: { filters: {} },
			freeze: false
		}).then((r) => {
			sp.classList.remove("umre-fin-loading");
			const data = r && r.message && r.message.operational_dashboard;
			console.log("OPERATIONAL DATA", data);
			if (!is_valid_operational_data(data)) {
				render_empty_operational_dashboard(sp, __("Operasyonel gider verisi eksik. Grafik çizilmeyecek."));
				return;
			}
			render_season_payload(sp, data);
		}).catch((err) => {
			sp.classList.remove("umre-fin-loading");
			console.error("Operational dashboard refresh failed", err);
			render_empty_operational_dashboard(sp, __("Operasyonel gider verisi alınamadı."));
		});
	}

	function is_valid_operational_data(data) {
		return Boolean(
			data &&
			Number.isFinite(Number(data.total_expense_usd || 0)) &&
			Array.isArray(data.by_main_category) &&
			Array.isArray(data.by_expense_item) &&
			Array.isArray(data.monthly_trend)
		);
	}

	function render_empty_operational_dashboard(sp, message) {
		sp.querySelector("#umre-season-total").innerHTML = `<div class="umre-fin-empty">${frappe.utils.escape_html(message)}</div>`;
		sp.querySelector("#umre-season-cards").innerHTML = "";
		const items = sp.querySelector("#umre-season-items");
		if (items) items.innerHTML = "";
		sp.querySelector("#umre-season-chart-cat").innerHTML = "";
		sp.querySelector("#umre-season-chart-month").innerHTML = "";
		_season_state.chart_cat = null;
		_season_state.chart_month = null;
	}

	function render_season_payload(sp, data) {
		const rows = data.by_main_category || [];
		const items = data.by_expense_item || [];
		const trend = data.monthly_trend || [];
		const total = Number(data.total_expense_usd || 0);
		const activeSeason = data.active_season || "";

		const hero = sp.querySelector("#umre-season-total");
		hero.innerHTML = [
			hero_cell("cost", __("Toplam Gider"), fmt_money(total, "USD"), activeSeason ? __("Aktif Sezon") + ": " + activeSeason : "")
		].join("");

		const cards = sp.querySelector("#umre-season-cards");
		const emptyMsg = __("Bu sezon için onaylı genel gider bulunmuyor.");
		cards.innerHTML = rows.length ? rows.map((row, idx) => {
			const value = Number(row.value || 0);
			const share = total > 0 ? value / total : 0;
			const color = COST_COLORS[idx % COST_COLORS.length];
			return `
				<div class="umre-fin-cost-card" style="--cost-color:${color}">
					<div class="umre-fin-cost-card__label">${frappe.utils.escape_html(row.label || __("Kategori"))}</div>
					<div class="umre-fin-cost-card__amount">${fmt_money(value, "USD")}</div>
					<div class="umre-fin-cost-card__share">${fmt_pct(share)}</div>
				</div>`;
		}).join("") : `<div class="umre-fin-empty">${emptyMsg}</div>`;

		const itemHost = sp.querySelector("#umre-season-items");
		if (itemHost) {
			itemHost.innerHTML = items.length ? `
				<div class="frappe-card p-3">
					${items.map((row) => `
						<div style="display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px solid var(--border-color);">
							<div>
								<div>${frappe.utils.escape_html(row.label || __("Gider Kalemi"))}</div>
								<div class="text-muted small">${frappe.utils.escape_html(row.parent_label || "")}</div>
							</div>
							<div style="font-weight:700;">${fmt_money(Number(row.value || 0), "USD")}</div>
						</div>
					`).join("")}
				</div>` : `<div class="umre-fin-empty">${emptyMsg}</div>`;
		}

		const hostCat = sp.querySelector("#umre-season-chart-cat");
		hostCat.innerHTML = "";
		_season_state.chart_cat = null;
		const catLabels = rows.map((x) => x.label);
		const catValues = rows.map((x) => Number(x.value || 0));
		if (catLabels.length && typeof frappe.Chart === "function") {
			_season_state.chart_cat = new frappe.Chart(hostCat, {
				type: "donut",
				data: { labels: catLabels, datasets: [{ values: catValues }] },
				height: 240,
				colors: COST_COLORS
			});
		} else {
			hostCat.innerHTML = `<div class="umre-fin-empty">${__("Kayıt yok")}</div>`;
		}

		const hostM = sp.querySelector("#umre-season-chart-month");
		hostM.innerHTML = "";
		_season_state.chart_month = null;
		const monthLabels = trend.map((x) => x.month);
		const monthValues = trend.map((x) => Number(x.value || 0));
		if (monthLabels.length && typeof frappe.Chart === "function") {
			_season_state.chart_month = new frappe.Chart(hostM, {
				type: "line",
				data: { labels: monthLabels, datasets: [{ name: "USD", values: monthValues }] },
				height: 240,
				colors: ["#0ea5e9"]
			});
		} else {
			hostM.innerHTML = `<div class="umre-fin-empty">${__("Trend yok")}</div>`;
		}
	}

	function refresh() {
		const panel = document.getElementById(PANEL_ID);
		if (!panel) return;
		_state.loading = true;
		panel.classList.add("umre-fin-loading");

		frappe.call({
			method: ENDPOINT,
			args: { tour: _state.tour || "", _: Date.now() },
			freeze: false
		}).then((r) => {
			_state.loading = false;
			panel.classList.remove("umre-fin-loading");
			const data = r && r.message;
			console.log("DASHBOARD DATA", data);
			if (!is_valid_dashboard_data(data)) {
				render_empty_dashboard(panel, __("Dashboard verisi eksik veya boş. Maliyet bileşenleri oluşmadan grafik çizilemez."));
				return;
			}
			_state.last_payload = data;
			render_payload(panel, data);
		}).catch((err) => {
			_state.loading = false;
			panel.classList.remove("umre-fin-loading");
			console.error("Umre cost dashboard refresh failed", err);
			render_empty_dashboard(panel, __("Dashboard verisi alınamadı."));
		});
	}

	function is_valid_dashboard_data(data) {
		return Boolean(
			data &&
			data.kpis &&
			Array.isArray(data.cost_breakdown) &&
			data.cost_breakdown.length &&
			data.performance &&
			data.meta
		);
	}

	function render_empty_dashboard(panel, message) {
		panel.querySelector("#umre-fin-hero").innerHTML = `<div class="umre-fin-empty">${frappe.utils.escape_html(message)}</div>`;
		panel.querySelector("#umre-fin-cards").innerHTML = "";
		panel.querySelector("#umre-fin-chart").innerHTML = `<div class="umre-fin-empty">${frappe.utils.escape_html(message)}</div>`;
		panel.querySelector("#umre-fin-kpi").innerHTML = "";
		_state.chart = null;
	}

	function render_payload(panel, p) {
		const k = p.kpis || {};
		const rows = (p.cost_breakdown || []).map((row, idx) => ({
			label: row.label || __("Maliyet"),
			value: Number(row.value || 0),
			color: COST_COLORS[idx % COST_COLORS.length]
		}));
		const perf = p.performance || {};
		const meta = p.meta || {};
		const currency = p.currency || "USD";

		// Tour selector population (preserve current selection).
		const sel = panel.querySelector("#umre-fin-tour");
		const current = _state.tour;
		const opts = [`<option value="">${__("Tüm Turlar")}</option>`].concat(
			(p.tours || []).map((t) => `<option value="${frappe.utils.escape_html(t.name)}">${frappe.utils.escape_html(t.label)}</option>`)
		);
		sel.innerHTML = opts.join("");
		sel.value = current;

		// Hero strip.
		const hero = panel.querySelector("#umre-fin-hero");
		const profit_loss = (k.net_profit || 0) < 0 ? "is-loss" : "";
		hero.innerHTML = [
			hero_cell("revenue", __("Gelir"), fmt_money(k.total_revenue, currency), ""),
			hero_cell("cost", __("Toplam Maliyet"), fmt_money(k.total_cost, currency), __("Kişi sayısı") + ": " + fmt_int(meta.kisi_sayisi)),
			hero_cell("profit " + profit_loss, __("Net Kar"), fmt_money(k.net_profit, currency), "")
		].join("");

		// Cost cards from the strict API contract: cost_breakdown[{label, value}].
		const cards = panel.querySelector("#umre-fin-cards");
		const total = Number(k.total_cost || 0);
		cards.innerHTML = rows.map((c) => {
			const amt = Number(c.value || 0);
			const share = total > 0 ? (amt / total) : 0;
			const zero_class = amt > 0 ? "" : " is-zero";
			return `
				<div class="umre-fin-cost-card${zero_class}" style="--cost-color:${c.color}">
					<div class="umre-fin-cost-card__label">${frappe.utils.escape_html(c.label)}</div>
					<div class="umre-fin-cost-card__amount">${fmt_money(amt, currency)}</div>
					<div class="umre-fin-cost-card__share">${fmt_pct(share)}</div>
				</div>`;
		}).join("");

		// Doughnut.
		render_chart(panel, p);

		// KPIs.
		const kpi = panel.querySelector("#umre-fin-kpi");
		const kbk_cls = (perf.profit_per_person || 0) < 0 ? "is-loss" : "";
		kpi.innerHTML = [
			kpi_cell("cost", __("Kişi Başı Maliyet"), fmt_money(perf.cost_per_person, currency)),
			kpi_cell("profit " + kbk_cls, __("Kişi Başı Kar"), fmt_money(perf.profit_per_person, currency)),
			kpi_cell("ratio", __("Yemek Oranı"), fmt_pct_value(perf.food_ratio))
		].join("");
	}

	function hero_cell(kind, label, value, sub) {
		return `
			<div class="umre-fin-hero__cell umre-fin-hero__cell--${kind}">
				<div class="umre-fin-hero__label">${frappe.utils.escape_html(label)}</div>
				<div class="umre-fin-hero__value">${value}</div>
				<div class="umre-fin-hero__sub">${frappe.utils.escape_html(sub)}</div>
			</div>`;
	}

	function kpi_cell(kind, label, value) {
		return `
			<div class="umre-fin-kpi__cell umre-fin-kpi__cell--${kind}">
				<div class="umre-fin-kpi__label">${frappe.utils.escape_html(label)}</div>
				<div class="umre-fin-kpi__value">${value}</div>
			</div>`;
	}

	function render_chart(panel, p) {
		const host = panel.querySelector("#umre-fin-chart");
		host.innerHTML = ""; // reset
		const rows = p.cost_breakdown || [];
		const labels = rows.map((x) => x.label);
		const values = rows.map((x) => Number(x.value || 0));
		if (!labels.length) {
			host.innerHTML = `<div class="umre-fin-empty">${__("Maliyet bileşeni bulunamadı.")}</div>`;
			_state.chart = null;
			return;
		}
		// Frappe Charts is bundled with desk; defer to it.
		if (typeof frappe.Chart !== "function") {
			host.innerHTML = `<div class="umre-fin-empty">${__("Grafik kütüphanesi yüklenmedi.")}</div>`;
			return;
		}
		const shareTot = values.reduce((sum, value) => sum + value, 0);
		const currency = p.currency || "USD";
		_state.chart = new frappe.Chart(host, {
			type: "donut",
			data: {
				labels: labels,
				datasets: [{ values: values }]
			},
			height: 280,
			colors: COST_COLORS,
			truncateLegends: false,
			tooltipOptions: {
				formatTooltipY: (d) => {
					const v = Number(d || 0);
					const pct = shareTot > 0 ? ((v / shareTot) * 100).toFixed(1) : "0.0";
					return fmt_money(v, currency) + " (" + pct + "%)";
				}
			}
		});
	}

	// --- bootstrap -----------------------------------------------------

	function bootstrap() {
		// Mount on every route change AND on initial DOM ready.
		$(document).on("app_ready page-change", ensure_mounted);

		// Frappe v14 emits `change` on its router.
		if (frappe.router && frappe.router.on) {
			frappe.router.on("change", ensure_mounted);
		}

		// Watch for workspace re-renders (Frappe re-mounts the codex editor
		// when switching workspaces); MutationObserver is the safety net.
		const obs = new MutationObserver(() => {
			ensure_mounted();
		});
		obs.observe(document.body, { childList: true, subtree: true });

		// Realtime: refresh on any cost-component dirty signal. Debounce
		// because component generation fires 6 events per booking.
		if (frappe.realtime && frappe.realtime.on) {
			frappe.realtime.on("umre_cost_dashboard_dirty", () => {
				const btn = document.getElementById("umre-fin-refresh");
				if (btn) btn.classList.add("is-stale");
				schedule_refresh(800);
			});
			frappe.realtime.on("umre_operational_expense_dirty", () => {
				schedule_season_refresh(500);
			});
		}

		// Also refresh whenever an Umre Booking or Cost Component is saved
		// from anywhere in the desk (covers the "after booking insert" rule
		// even without a realtime event from the server).
		$(document).on("after_save", function (_evt, doc) {
			if (!doc) return;
			if (
				doc.doctype === "Umre Booking" ||
				doc.doctype === "Cost Component" ||
				doc.doctype === "Umre Tour" ||
				doc.doctype === "Tour Cost Configuration" ||
				doc.doctype === "Meal Cost Rule" ||
				doc.doctype === "Other Cost Rule"
			) {
				schedule_refresh(500);
			}
			if (doc.doctype === "Operational Expense") {
				schedule_season_refresh(400);
			}
		});

		// Initial mount attempt.
		ensure_mounted();
	}

	if (typeof frappe !== "undefined") {
		$(document).ready(bootstrap);
	}
})();
