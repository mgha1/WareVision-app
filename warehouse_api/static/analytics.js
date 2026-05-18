(function () {
  var lastUpdated = document.getElementById("analytics-last-updated");
  var activeSkus = document.getElementById("analytics-active-skus");
  var totalUnits = document.getElementById("analytics-total-units");
  var occupancyRate = document.getElementById("analytics-occupancy-rate");
  var activeAssets = document.getElementById("analytics-active-assets");
  var pendingQueue = document.getElementById("analytics-pending-queue");
  var queueSavings = document.getElementById("analytics-queue-savings");
  var inboundUnits = document.getElementById("analytics-inbound-units");
  var todayRevenue = document.getElementById("analytics-today-revenue");
  var zoneUtilization = document.getElementById("analytics-zone-utilization");
  var assetStatus = document.getElementById("analytics-asset-status");
  var recommendationStatus = document.getElementById("analytics-recommendation-status");
  var inboundActivity = document.getElementById("analytics-inbound-activity");
  var salesTrend = document.getElementById("analytics-sales-trend");
  var topSkus = document.getElementById("analytics-top-skus");
  var categoryMix = document.getElementById("analytics-category-mix");

  if (!lastUpdated) {
    return;
  }

  var state = {
    authenticated: false,
    timerId: null
  };

  function getApiFetch() {
    return window.warehouseFetch || fetch;
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString();
  }

  function formatCurrency(value) {
    return "$" + Number(value || 0).toLocaleString(undefined, {
      maximumFractionDigits: 0
    });
  }

  function formatMeters(value) {
    return Number(value || 0).toLocaleString(undefined, {
      maximumFractionDigits: 1
    }) + " m";
  }

  function formatPercent(value) {
    return Number(value || 0).toFixed(1) + "%";
  }

  function zoneBarColor(value) {
    var percent = Number(value || 0);
    if (percent > 90) {
      return "#ef6b62";
    }
    if (percent >= 70) {
      return "#efb04c";
    }
    return "#40a96b";
  }

  function formatTime(value) {
    if (!value) {
      return "-";
    }
    return new Date(value).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function renderEmptyTable(node, colspan, text) {
    clearNode(node);
    var row = document.createElement("tr");
    var cell = document.createElement("td");
    cell.colSpan = colspan;
    cell.className = "table-empty";
    cell.textContent = text;
    row.appendChild(cell);
    node.appendChild(row);
  }

  function renderZoneUtilization(items) {
    var storageZones = (items || []).filter(function (zone) {
      var zoneName = String(zone.zone_name || "").toUpperCase();
      var zoneType = String(zone.zone_type || "").toUpperCase();
      return (
        zoneName.indexOf("BULK") !== -1 ||
        zoneType.indexOf("BULK") !== -1 ||
        zoneType.indexOf("STORE") !== -1 ||
        zoneName.indexOf("FAST") !== -1 ||
        zoneType.indexOf("FAST") !== -1 ||
        zoneType.indexOf("PICK") !== -1
      );
    });

    clearNode(zoneUtilization);

    if (!storageZones.length) {
      zoneUtilization.textContent = "No zone telemetry available.";
      return;
    }

    storageZones.forEach(function (zone) {
      var card = document.createElement("article");
      var header = document.createElement("div");
      var title = document.createElement("div");
      var metric = document.createElement("strong");
      var bar = document.createElement("div");
      var fill = document.createElement("div");
      var meta = document.createElement("div");

      card.className = "analytics-zone-card";
      header.className = "analytics-zone-header";
      title.className = "analytics-zone-title";
      metric.className = "analytics-zone-metric";
      bar.className = "analytics-progress";
      fill.className = "analytics-progress-fill";
      meta.className = "analytics-zone-meta";

      title.innerHTML =
        "<strong>" + (zone.zone_name || zone.zone_id || "-") + "</strong>" +
        "<span>" + (zone.zone_type || "-") + "</span>";
      metric.textContent = formatPercent(zone.occupancy_pct);
      fill.style.width = String(Math.max(0, Math.min(100, Number(zone.occupancy_pct || 0)))) + "%";
      fill.style.background = zoneBarColor(zone.occupancy_pct);
      meta.innerHTML =
        "<span>" + formatNumber(zone.occupied_slots) + " / " + formatNumber(zone.total_slots) + " slots used</span>" +
        "<span>" + formatNumber(zone.sku_count) + " SKUs</span>" +
        "<span>" + formatNumber(zone.pick_count_30d) + " picks / 30d</span>";

      bar.appendChild(fill);
      header.appendChild(title);
      header.appendChild(metric);
      card.appendChild(header);
      card.appendChild(bar);
      card.appendChild(meta);
      zoneUtilization.appendChild(card);
    });
  }

  function renderChipList(node, items, valueKey, formatter) {
    clearNode(node);
    if (!items.length) {
      node.textContent = "No data available.";
      return;
    }

    items.forEach(function (item) {
      var chip = document.createElement("div");
      chip.className = "analytics-status-chip";
      chip.innerHTML =
        "<span>" + (item.status || item.hour_bucket || item.sale_date || "-") + "</span>" +
        "<strong>" + formatter(item[valueKey]) + "</strong>";
      node.appendChild(chip);
    });
  }

  function renderBarList(node, items, labelKey, valueKey, formatter) {
    clearNode(node);
    if (!items.length) {
      node.textContent = "No activity recorded.";
      return;
    }

    var maxValue = items.reduce(function (max, item) {
      return Math.max(max, Number(item[valueKey] || 0));
    }, 0);

    items.forEach(function (item) {
      var row = document.createElement("div");
      var label = document.createElement("span");
      var value = document.createElement("strong");
      var rail = document.createElement("div");
      var fill = document.createElement("div");

      row.className = "analytics-bar-row";
      label.className = "analytics-bar-label";
      value.className = "analytics-bar-value";
      rail.className = "analytics-progress analytics-progress-compact";
      fill.className = "analytics-progress-fill";

      label.textContent = item[labelKey] || "-";
      value.textContent = formatter(item[valueKey]);
      fill.style.width = maxValue ? ((Number(item[valueKey] || 0) / maxValue) * 100) + "%" : "0%";

      rail.appendChild(fill);
      row.appendChild(label);
      row.appendChild(rail);
      row.appendChild(value);
      node.appendChild(row);
    });
  }

  function renderTopSkus(items) {
    clearNode(topSkus);
    if (!items.length) {
      renderEmptyTable(topSkus, 6, "No pick history available.");
      return;
    }

    items.forEach(function (item) {
      var row = document.createElement("tr");
      [
        item.sku_id || "-",
        item.sku_name || "-",
        formatNumber(item.total_picks),
        formatNumber(item.quantity_on_hand),
        item.current_slot || "-",
        item.zone_name || "-"
      ].forEach(function (value) {
        var cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });
      topSkus.appendChild(row);
    });
  }

  function renderCategoryMix(items) {
    clearNode(categoryMix);
    if (!items.length) {
      renderEmptyTable(categoryMix, 5, "No category analytics available.");
      return;
    }

    items.forEach(function (item) {
      var row = document.createElement("tr");
      [
        item.category || "Uncategorized",
        formatNumber(item.sku_count),
        formatNumber(item.quantity_on_hand),
        formatNumber(item.picks_30d),
        formatCurrency(item.revenue_7d)
      ].forEach(function (value) {
        var cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });
      categoryMix.appendChild(row);
    });
  }

  function renderAnalytics(payload) {
    var summary = payload.summary || {};

    activeSkus.textContent = formatNumber(summary.active_skus);
    totalUnits.textContent = formatNumber(summary.total_units);
    occupancyRate.textContent = formatPercent(summary.occupancy_rate);
    activeAssets.textContent = formatNumber(summary.active_assets);
    pendingQueue.textContent = formatNumber(summary.pending_recommendations);
    queueSavings.textContent = formatMeters(summary.queue_savings_m);
    inboundUnits.textContent = formatNumber(summary.today_inbound_units);
    todayRevenue.textContent = formatCurrency(summary.today_revenue);
    lastUpdated.textContent = "Updated " + formatTime(new Date());

    renderZoneUtilization(payload.zone_utilization || []);
    renderChipList(assetStatus, payload.asset_status || [], "asset_count", formatNumber);
    renderChipList(
      recommendationStatus,
      (payload.recommendation_status || []).map(function (item) {
        return {
          status: item.status,
          recommendation_count: item.recommendation_count,
          display_value: formatNumber(item.recommendation_count) + " / " + formatMeters(item.total_saving_m)
        };
      }),
      "display_value",
      function (value) {
        return value;
      }
    );
    renderBarList(inboundActivity, payload.inbound_activity || [], "hour_bucket", "inbound_units", formatNumber);
    renderBarList(salesTrend, payload.sales_trend || [], "sale_date", "revenue", formatCurrency);
    renderTopSkus(payload.top_skus || []);
    renderCategoryMix(payload.category_mix || []);
  }

  function loadAnalytics() {
    if (!state.authenticated) {
      lastUpdated.textContent = "Sign in to load analytics";
      return;
    }

    getApiFetch()("/api/analytics")
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (payload) {
            throw new Error(payload.detail || "Analytics request failed");
          });
        }
        return response.json();
      })
      .then(renderAnalytics)
      .catch(function (error) {
        lastUpdated.textContent = error.message;
        renderEmptyTable(topSkus, 6, error.message);
        renderEmptyTable(categoryMix, 5, error.message);
        zoneUtilization.textContent = error.message;
        assetStatus.textContent = error.message;
        recommendationStatus.textContent = error.message;
        inboundActivity.textContent = error.message;
        salesTrend.textContent = error.message;
      });
  }

  function startPolling() {
    if (state.timerId) {
      window.clearInterval(state.timerId);
    }
    state.timerId = window.setInterval(loadAnalytics, 30000);
  }

  function stopPolling() {
    if (state.timerId) {
      window.clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  window.addEventListener("warehouse-auth-changed", function (event) {
    var detail = event.detail || {};
    state.authenticated = !!detail.authenticated;
    if (state.authenticated) {
      loadAnalytics();
      startPolling();
      return;
    }

    stopPolling();
    lastUpdated.textContent = "Sign in to load analytics";
    renderEmptyTable(topSkus, 6, "Sign in to load analytics.");
    renderEmptyTable(categoryMix, 5, "Sign in to load analytics.");
  });

  window.addEventListener("inventory-assigned", loadAnalytics);
  window.addEventListener("recommendation-accepted", loadAnalytics);

  if (window.WarehouseShell && window.WarehouseShell.isAuthenticated()) {
    state.authenticated = true;
    loadAnalytics();
    startPolling();
  } else {
    renderEmptyTable(topSkus, 6, "Sign in to load analytics.");
    renderEmptyTable(categoryMix, 5, "Sign in to load analytics.");
    lastUpdated.textContent = "Sign in to load analytics";
  }
}());
