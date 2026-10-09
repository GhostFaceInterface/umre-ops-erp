/*
 * Umre Operasyon Paneli — Financial Dashboard
 *
 * Mounts two panels above the "Umre Operasyon Paneli" workspace cards and
 * refetches on realtime `umre_cost_dashboard_dirty` / `umre_operational_expense_dirty`.
 *
 * All numbers are computed on the server (`pnl_service`, shared with the Tour
 * Revenue Summary report); this file only renders them.
 */
(function () {
	"use strict";

	const PANEL_ID = "umre-fin-panel";
	const WORKSPACE_ROUTES = ["umre-operasyon-paneli", "Umre Operasyon Paneli"];
	const ENDPOINT = "umre_ops.umre_ops.services.dashboard_service.get_tour_cost_breakdown";
	const SEASON_PANEL_ID = "umre-season-fin-panel";
	const SEASON_ENDPOINT = "umre_ops.umre_ops.services.dashboard_service.get_operational_dashboard_data";
	const CATEGORY_COLORS = ["#ff4d4f", "#ff7a45", "#ffa940", "#36cfc9", "#597ef7", "#9254de", "#13c2c2"];
	const RULE_DOCTYPES = new Set([
		"Umre Tour",
		"Umre Booking",
		"Tour Hotel Cost Rule",
		"Tour Airfare Cost Rule",
		"Tour Visa Cost Rule",
		"Tour Diyanet Card Rule",
		"Meal Cost Rule",
		"Other Cost Rule",
	]);

	const _state = {
		season: "", // "" = backend selects active season
		tour: "", // "" = all tours
		debounce_handle: null,
		request_seq: 0,
		chart: null,
	};
	const _season_state = {
		request_seq: 0,
		chart_cat: null,
		chart_month: null,
	};

	const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

	function fmt_money(value, currency) {
		const n = Number(value || 0);
		const cur = (currency || "USD").toString().toUpperCase();
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
		return cur + " " + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	function fmt_pct(value) {
		return (Number(value || 0) * 100).toFixed(1) + "%";
	}

	function fmt_pct_value(value) {
		return Number(value || 0).toFixed(1) + "%";
	}

	function fmt_int(value) {
		return Number(value || 0).toLocaleString("tr-TR");
	}

	function destroy_chart(chart) {
		if (chart && typeof chart.destroy === "function") {
			try {
				chart.destroy();
			} catch (e) {
				/* already detached */
			}
		}
		return null;
	}

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
			_state.chart = destroy_chart(_state.chart);
			_season_state.chart_cat = destroy_chart(_season_state.chart_cat);
			_season_state.chart_month = destroy_chart(_season_state.chart_month);
			return;
		}

		const candidates = [
			document.querySelector(".workspace-sidebar-toggle ~ .codex-editor"),
			document.querySelector(".layout-main-section .codex-editor"),
			document.querySelector(".codex-editor"),
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
				<div class="umre-fin-panel__title"><span class="dot"></span>${__("Tur Kâr / Zarar Paneli")}</div>
				<div class="umre-fin-panel__filter">
					<label for="umre-fin-season">${__("Sezon")}</label>
					<select id="umre-fin-season"></select>
					<label for="umre-fin-tour">${__("Tur")}</label>
					<select id="umre-fin-tour"><option value="">${esc(__("Tüm Turlar"))}</option></select>
					<button type="button" class="umre-fin-panel__refresh" id="umre-fin-refresh">${__("Yenile")}</button>
				</div>
			</div>
			<div class="umre-fin-hero" id="umre-fin-hero"></div>
			<div class="umre-fin-hero" id="umre-fin-season-result"></div>
			<div id="umre-fin-warnings"></div>

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
				<div class="umre-fin-section__title">${__("Performans ve Tahsilat")}</div>
				<div class="umre-fin-section__rule"></div>
			</div>
			<div class="umre-fin-kpi" id="umre-fin-kpi"></div>
		`;
	}

	function wire_events(panel) {
		const seasonSel = panel.querySelector("#umre-fin-season");
		seasonSel.addEventListener("change", function () {
			_state.season = seasonSel.value || "";
			_state.tour = "";
			schedule_refresh(0);
			schedule_season_refresh(0);
		});
		const sel = panel.querySelector("#umre-fin-tour");
		sel.addEventListener("change", function () {
			_state.tour = sel.value || "";
			schedule_refresh(0);
			schedule_season_refresh(0);
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
				<div class="umre-fin-panel__title umre-season-fin-panel__title"><span class="dot"></span><span id="umre-season-title">${__("Ofis Genel Giderleri")}</span></div>
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
				<div class="umre-fin-section__title">${__("Gider Grafikleri")}</div>
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
		const seq = ++_season_state.request_seq;
		const tour = _state.tour || "";
		sp.classList.add("umre-fin-loading");
		frappe
			.call({
				method: SEASON_ENDPOINT,
				args: { filters: { season: _state.season, tour: tour } },
				freeze: false,
			})
			.then((r) => {
				if (seq !== _season_state.request_seq) return;
				sp.classList.remove("umre-fin-loading");
				const data = r && r.message && r.message.operational_dashboard;
				if (!is_valid_operational_data(data)) {
					render_empty_operational_dashboard(sp, __("Gider verisi eksik. Grafik çizilmeyecek."));
					return;
				}
				render_season_payload(sp, data, tour);
			})
			.catch(() => {
				if (seq !== _season_state.request_seq) return;
				sp.classList.remove("umre-fin-loading");
				render_empty_operational_dashboard(sp, __("Gider verisi alınamadı."));
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
		sp.querySelector("#umre-season-total").innerHTML = `<div class="umre-fin-empty">${esc(message)}</div>`;
		sp.querySelector("#umre-season-cards").innerHTML = "";
		const items = sp.querySelector("#umre-season-items");
		if (items) items.innerHTML = "";
		_season_state.chart_cat = destroy_chart(_season_state.chart_cat);
		_season_state.chart_month = destroy_chart(_season_state.chart_month);
		sp.querySelector("#umre-season-chart-cat").innerHTML = "";
		sp.querySelector("#umre-season-chart-month").innerHTML = "";
	}

	function render_season_payload(sp, data, tour) {
		const rows = data.by_main_category || [];
		const items = data.by_expense_item || [];
		const trend = data.monthly_trend || [];
		const total = Number(data.total_expense_usd || 0);
		const is_tour = data.scope === "tour";

		sp.querySelector("#umre-season-title").textContent = is_tour
			? __("Tur Ekstra Giderleri")
			: __("Ofis Genel Giderleri");

		const subtitle = [
			data.active_season ? __("Sezon") + ": " + data.active_season : "",
			is_tour ? __("Tur") + ": " + tour : __("Turlara dağıtılmaz"),
			data.draft_count ? __("{0} taslak gider toplama dahil değil", [data.draft_count]) : "",
		]
			.filter(Boolean)
			.join(" · ");
		sp.querySelector("#umre-season-total").innerHTML = hero_cell(
			"cost",
			is_tour ? __("Tur Ekstra Gider") : __("Toplam Genel Gider"),
			fmt_money(total, "USD"),
			subtitle
		);

		const cards = sp.querySelector("#umre-season-cards");
		const emptyMsg = is_tour
			? __("Bu tur için onaylı ekstra gider bulunmuyor.")
			: __("Bu sezon için onaylı genel gider bulunmuyor.");
		cards.innerHTML = rows.length
			? rows
					.map((row, idx) => {
						const value = Number(row.value || 0);
						const share = total > 0 ? value / total : 0;
						const color = CATEGORY_COLORS[idx % CATEGORY_COLORS.length];
						return `
				<div class="umre-fin-cost-card" style="--cost-color:${color}">
					<div class="umre-fin-cost-card__label">${esc(row.label || __("Kategori"))}</div>
					<div class="umre-fin-cost-card__amount">${fmt_money(value, "USD")}</div>
					<div class="umre-fin-cost-card__share">${fmt_pct(share)}</div>
				</div>`;
					})
					.join("")
			: `<div class="umre-fin-empty">${emptyMsg}</div>`;

		const itemHost = sp.querySelector("#umre-season-items");
		if (itemHost) {
			itemHost.innerHTML = items.length
				? `
				<div class="frappe-card p-3">
					${items
						.map(
							(row) => `
						<div style="display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px solid var(--border-color);">
							<div>
								<div>${esc(row.label || __("Gider Kalemi"))}</div>
								<div class="text-muted small">${esc(row.parent_label || "")}</div>
							</div>
							<div style="font-weight:700;">${fmt_money(Number(row.value || 0), "USD")}</div>
						</div>`
						)
						.join("")}
				</div>`
				: `<div class="umre-fin-empty">${emptyMsg}</div>`;
		}

		const hostCat = sp.querySelector("#umre-season-chart-cat");
		_season_state.chart_cat = destroy_chart(_season_state.chart_cat);
		hostCat.innerHTML = "";
		if (rows.length && typeof frappe.Chart === "function") {
			_season_state.chart_cat = new frappe.Chart(hostCat, {
				type: "donut",
				data: { labels: rows.map((x) => x.label), datasets: [{ values: rows.map((x) => Number(x.value || 0)) }] },
				height: 240,
				colors: CATEGORY_COLORS,
			});
		} else {
			hostCat.innerHTML = `<div class="umre-fin-empty">${__("Kayıt yok")}</div>`;
		}

		const hostM = sp.querySelector("#umre-season-chart-month");
		_season_state.chart_month = destroy_chart(_season_state.chart_month);
		hostM.innerHTML = "";
		if (trend.length && typeof frappe.Chart === "function") {
			_season_state.chart_month = new frappe.Chart(hostM, {
				type: "line",
				data: { labels: trend.map((x) => x.month), datasets: [{ name: "USD", values: trend.map((x) => Number(x.value || 0)) }] },
				height: 240,
				colors: ["#0ea5e9"],
			});
		} else {
			hostM.innerHTML = `<div class="umre-fin-empty">${__("Trend yok")}</div>`;
		}
	}

	function refresh() {
		const panel = document.getElementById(PANEL_ID);
		if (!panel) return;
		const seq = ++_state.request_seq;
		panel.classList.add("umre-fin-loading");

		frappe
			.call({
				method: ENDPOINT,
				args: { season: _state.season, tour: _state.tour || "" },
				freeze: false,
			})
			.then((r) => {
				// A newer request (season / tour change) owns the panel now.
				if (seq !== _state.request_seq) return;
				panel.classList.remove("umre-fin-loading");
				const data = r && r.message;
				if (!is_valid_dashboard_data(data)) {
					render_empty_dashboard(panel, __("Dashboard verisi eksik veya boş."));
					return;
				}
				render_payload(panel, data);
			})
			.catch(() => {
				if (seq !== _state.request_seq) return;
				panel.classList.remove("umre-fin-loading");
				render_empty_dashboard(panel, __("Dashboard verisi alınamadı."));
			});
	}

	function is_valid_dashboard_data(data) {
		return Boolean(
			data &&
				data.kpis &&
				Array.isArray(data.cost_breakdown) &&
				data.performance &&
				data.meta &&
				Array.isArray(data.seasons) &&
				Array.isArray(data.tours)
		);
	}

	function render_empty_dashboard(panel, message) {
		panel.querySelector("#umre-fin-hero").innerHTML = `<div class="umre-fin-empty">${esc(message)}</div>`;
		panel.querySelector("#umre-fin-season-result").innerHTML = "";
		panel.querySelector("#umre-fin-warnings").innerHTML = "";
		panel.querySelector("#umre-fin-cards").innerHTML = "";
		_state.chart = destroy_chart(_state.chart);
		panel.querySelector("#umre-fin-chart").innerHTML = `<div class="umre-fin-empty">${esc(message)}</div>`;
		panel.querySelector("#umre-fin-kpi").innerHTML = "";
	}

	function populate_selectors(panel, p) {
		_state.season = p.selected_season || "";
		const seasonSel = panel.querySelector("#umre-fin-season");
		seasonSel.innerHTML = (p.seasons || [])
			.map((season) => `<option value="${esc(season.name)}">${esc(season.label || season.name)}</option>`)
			.join("");
		seasonSel.value = _state.season;

		const sel = panel.querySelector("#umre-fin-tour");
		const opts = [`<option value="">${esc(__("Tüm Turlar"))}</option>`].concat(
			(p.tours || []).map((t) => `<option value="${esc(t.name)}">${esc(t.label || t.name)}</option>`)
		);
		sel.innerHTML = opts.join("");
		const known = (p.tours || []).some((t) => t.name === _state.tour);
		_state.tour = known ? _state.tour : "";
		sel.value = _state.tour;
	}

	function render_warnings(panel, warnings) {
		const host = panel.querySelector("#umre-fin-warnings");
		if (!warnings || !warnings.length) {
			host.innerHTML = "";
			return;
		}
		const items = warnings
			.map((w) => {
				const details = Object.entries(w.details || {})
					.map(([k, v]) => `${esc(k)}: ${fmt_int(v)}`)
					.join(", ");
				return `<li><b>${fmt_int(w.count)}</b> ${esc(__("rezervasyon"))} — ${esc(w.message)}${details ? ` <span class="text-muted">(${details})</span>` : ""}</li>`;
			})
			.join("");
		host.innerHTML = `<div class="alert alert-warning" style="margin:8px 0"><ul style="margin:0;padding-left:18px">${items}</ul></div>`;
	}

	function render_payload(panel, p) {
		const k = p.kpis || {};
		const perf = p.performance || {};
		const coll = p.collections || {};
		const meta = p.meta || {};
		const currency = p.currency || "USD";
		const rows = (p.cost_breakdown || []).map((row) => ({
			label: row.label || __("Maliyet"),
			value: Number(row.value || 0),
			color: row.color || "#8c8c8c",
		}));

		populate_selectors(panel, p);

		const profit_class = Number(k.tour_profit || 0) < 0 ? "is-loss" : "";
		panel.querySelector("#umre-fin-hero").innerHTML = [
			hero_cell(
				"revenue",
				__("Net Satış"),
				fmt_money(k.net_sales, currency),
				`${__("Brüt")}: ${fmt_money(k.gross_sales, currency)} · ${__("Komisyon")}: ${fmt_money(k.commission, currency)}`
			),
			hero_cell(
				"cost",
				__("Toplam Maliyet"),
				fmt_money(k.total_cost, currency),
				`${__("Yolcu")}: ${fmt_money(k.passenger_cost, currency)} · ${__("Tur ekstra")}: ${fmt_money(k.tour_extra_expense, currency)}`
			),
			hero_cell(
				"profit " + profit_class,
				__("Tur Kârı"),
				fmt_money(k.tour_profit, currency),
				`${__("Yolcu")}: ${fmt_int(meta.total_count)} · ${__("Ücretli")}: ${fmt_int(meta.umreci_count)} · ${__("Ücretsiz")}: ${fmt_int(meta.non_umreci_count)}`
			),
		].join("");

		const seasonHost = panel.querySelector("#umre-fin-season-result");
		if (k.season_result === null || k.season_result === undefined) {
			seasonHost.innerHTML = "";
		} else {
			const season_class = Number(k.season_result || 0) < 0 ? "is-loss" : "";
			seasonHost.innerHTML = [
				hero_cell("cost", __("Ofis Genel Gideri"), fmt_money(k.overhead, currency), __("Turlara dağıtılmaz")),
				hero_cell(
					"profit " + season_class,
					__("Sezon Sonucu"),
					fmt_money(k.season_result, currency),
					__("Tur kârları toplamı − genel gider")
				),
			].join("");
		}

		render_warnings(panel, p.warnings);

		const total = rows.reduce((sum, row) => sum + row.value, 0);
		panel.querySelector("#umre-fin-cards").innerHTML = rows
			.map((c) => {
				const share = total > 0 ? c.value / total : 0;
				return `
				<div class="umre-fin-cost-card${c.value > 0 ? "" : " is-zero"}" style="--cost-color:${c.color}">
					<div class="umre-fin-cost-card__label">${esc(c.label)}</div>
					<div class="umre-fin-cost-card__amount">${fmt_money(c.value, currency)}</div>
					<div class="umre-fin-cost-card__share">${fmt_pct(share)}</div>
				</div>`;
			})
			.join("");

		render_chart(panel, rows, currency);

		const per_person_class = Number(perf.profit_per_paying_passenger || 0) < 0 ? "is-loss" : "";
		panel.querySelector("#umre-fin-kpi").innerHTML = [
			kpi_cell("profit " + per_person_class, __("Ücretli Yolcu Başı Kâr"), fmt_money(perf.profit_per_paying_passenger, currency)),
			kpi_cell("cost", __("Yolcu Başı Maliyet"), fmt_money(perf.cost_per_person, currency)),
			kpi_cell("ratio", __("Yemek Oranı"), fmt_pct_value(perf.food_ratio)),
			kpi_cell("revenue", __("Tahsil Edilen"), fmt_money(coll.collected, currency)),
			kpi_cell("cost", __("Açık Alacak"), fmt_money(coll.open_receivable, currency)),
			kpi_cell("ratio", __("Excel'e Göre Ödenen"), fmt_money(coll.excel_reported, currency)),
		].join("");
	}

	function hero_cell(kind, label, value, sub) {
		return `
			<div class="umre-fin-hero__cell umre-fin-hero__cell--${kind}">
				<div class="umre-fin-hero__label">${esc(label)}</div>
				<div class="umre-fin-hero__value">${value}</div>
				<div class="umre-fin-hero__sub">${esc(sub)}</div>
			</div>`;
	}

	function kpi_cell(kind, label, value) {
		return `
			<div class="umre-fin-kpi__cell umre-fin-kpi__cell--${kind}">
				<div class="umre-fin-kpi__label">${esc(label)}</div>
				<div class="umre-fin-kpi__value">${value}</div>
			</div>`;
	}

	function render_chart(panel, rows, currency) {
		const host = panel.querySelector("#umre-fin-chart");
		_state.chart = destroy_chart(_state.chart);
		host.innerHTML = "";
		const values = rows.map((x) => x.value);
		const shareTot = values.reduce((sum, value) => sum + value, 0);
		if (!rows.length || shareTot <= 0) {
			host.innerHTML = `<div class="umre-fin-empty">${__("Maliyet bileşeni bulunamadı.")}</div>`;
			return;
		}
		if (typeof frappe.Chart !== "function") {
			host.innerHTML = `<div class="umre-fin-empty">${__("Grafik kütüphanesi yüklenmedi.")}</div>`;
			return;
		}
		_state.chart = new frappe.Chart(host, {
			type: "donut",
			data: { labels: rows.map((x) => x.label), datasets: [{ values: values }] },
			height: 280,
			colors: rows.map((x) => x.color),
			truncateLegends: false,
			tooltipOptions: {
				formatTooltipY: (d) => {
					const v = Number(d || 0);
					const pct = shareTot > 0 ? ((v / shareTot) * 100).toFixed(1) : "0.0";
					return fmt_money(v, currency) + " (" + pct + "%)";
				},
			},
		});
	}

	// --- bootstrap -----------------------------------------------------

	function bootstrap() {
		$(document).on("app_ready page-change", ensure_mounted);
		if (frappe.router && frappe.router.on) {
			frappe.router.on("change", ensure_mounted);
		}

		// Workspace re-renders replace the editor DOM; re-mount at most once per frame.
		let mount_scheduled = false;
		const obs = new MutationObserver(() => {
			if (mount_scheduled) return;
			mount_scheduled = true;
			window.requestAnimationFrame(() => {
				mount_scheduled = false;
				ensure_mounted();
			});
		});
		obs.observe(document.body, { childList: true, subtree: true });

		if (frappe.realtime && frappe.realtime.on) {
			frappe.realtime.on("umre_cost_dashboard_dirty", () => {
				if (!document.getElementById(PANEL_ID)) return;
				const btn = document.getElementById("umre-fin-refresh");
				if (btn) btn.classList.add("is-stale");
				schedule_refresh(800);
			});
			frappe.realtime.on("umre_operational_expense_dirty", () => {
				if (!document.getElementById(SEASON_PANEL_ID)) return;
				schedule_season_refresh(500);
				schedule_refresh(800);
			});
		}

		// Frappe triggers `save` on document after a form save.
		$(document).on("save", function (_evt, doc) {
			if (!doc) return;
			if (RULE_DOCTYPES.has(doc.doctype)) schedule_refresh(500);
			if (doc.doctype === "Operational Expense") {
				schedule_season_refresh(400);
				schedule_refresh(600);
			}
		});

		ensure_mounted();
	}

	if (typeof frappe !== "undefined") {
		$(document).ready(bootstrap);
	}
})();
