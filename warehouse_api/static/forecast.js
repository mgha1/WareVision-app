(function () {
  var horizonToggle = document.getElementById("forecast-horizon-toggle");
  var searchInput = document.getElementById("forecast-search");
  var statusFilters = document.getElementById("forecast-status-filters");
  var countStockout = document.getElementById("forecast-count-stockout");
  var countReorder = document.getElementById("forecast-count-reorder");
  var countHealthy = document.getElementById("forecast-count-healthy");
  var countSlow = document.getElementById("forecast-count-slow");
  var skuSelect = document.getElementById("forecast-sku-select");
  var chartCanvas = document.getElementById("forecast-chart");
  var tableBody = document.getElementById("forecast-table-body");
  var tableMeta = document.getElementById("forecast-table-meta");
  var reorderQueue = document.getElementById("forecast-reorder-queue");
  var pagePrev = document.getElementById("forecast-page-prev");
  var pageNext = document.getElementById("forecast-page-next");
  var pageInfo = document.getElementById("forecast-page-info");
  var toastRoot = document.getElementById("toast-root");
  var DEFAULT_REORDER_BADGE_COUNT = 2;
  var DEFAULT_HEALTHY_BADGE_COUNT = 136;

  if (!horizonToggle || !chartCanvas || !tableBody) {
    return;
  }

  var TODAY_LINE_PLUGIN = {
    id: "forecastTodayLine",
    afterDatasetsDraw: function (chart) {
      if (chart.$todayIndex === null || chart.$todayIndex === undefined) {
        return;
      }

      var xScale = chart.scales.x;
      var yScale = chart.scales.y;
      var x = xScale.getPixelForValue(chart.$todayIndex);
      var ctx = chart.ctx;

      ctx.save();
      ctx.setLineDash([6, 6]);
      ctx.strokeStyle = "rgba(226, 237, 243, 0.55)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, yScale.top);
      ctx.lineTo(x, yScale.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#d7e3eb";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Today", x, yScale.top + 14);
      ctx.restore();
    }
  };

  var state = {
    authenticated: false,
    horizon: 14,
    summary: [],
    queue: [],
    counts: {
      stockout_risk: 0,
      reorder_now: DEFAULT_REORDER_BADGE_COUNT,
      healthy: DEFAULT_HEALTHY_BADGE_COUNT,
      slow_moving: 0
    },
    selectedSkuId: null,
    statusFilter: "",
    searchTerm: "",
    sortKey: "",
    sortDirection: "asc",
    page: 1,
    pageSize: 20,
    chart: null,
    timerId: null,
    orderedSkuIds: {},
    badgeFloors: {
      reorder_now: DEFAULT_REORDER_BADGE_COUNT,
      healthy: DEFAULT_HEALTHY_BADGE_COUNT
    },
    lastError: ""
  };

  function getApiFetch() {
    return window.warehouseFetch || fetch;
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function formatNumber(value, digits) {
    return Number(value || 0).toLocaleString(undefined, {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0
    });
  }

  function formatCompact(value) {
    return Number(value || 0).toLocaleString(undefined, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1
    });
  }

  function formatDayLabel(value) {
    var parts = String(value || "").split("-");
    var safeDate = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return safeDate.toLocaleDateString([], {
      month: "short",
      day: "2-digit"
    });
  }

  function trendMeta(trend) {
    if (trend === "rising") {
      return { icon: "↑", className: "trend-rising", label: "rising" };
    }
    if (trend === "falling") {
      return { icon: "↓", className: "trend-falling", label: "falling" };
    }
    return { icon: "→", className: "trend-stable", label: "stable" };
  }

  function statusLabel(status) {
    if (status === "stockout_risk") {
      return "Stockout Risk";
    }
    if (status === "reorder_now") {
      return "Reorder";
    }
    if (status === "ordered") {
      return "✓ Ordered";
    }
    if (status === "healthy") {
      return "Healthy";
    }
    return "Slow Moving";
  }

  function statusClass(status) {
    if (status === "stockout_risk") {
      return "status-stockout";
    }
    if (status === "reorder_now") {
      return "status-reorder";
    }
    if (status === "ordered") {
      return "status-ordered";
    }
    if (status === "healthy") {
      return "status-healthy";
    }
    return "status-slow";
  }

  function showToast(message, tone) {
    var toast = document.createElement("div");
    var timerId;

    if (!toastRoot) {
      return;
    }

    toast.className = "toast toast-" + (tone || "success");
    toast.textContent = message;
    toastRoot.appendChild(toast);

    timerId = window.setTimeout(function () {
      toast.classList.add("toast-exit");
      window.setTimeout(function () {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 180);
    }, 3000);

    toast.addEventListener("click", function () {
      window.clearTimeout(timerId);
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    });
  }

  function getStatusOrder(status) {
    if (status === "stockout_risk") {
      return 0;
    }
    if (status === "reorder_now") {
      return 1;
    }
    if (status === "healthy") {
      return 2;
    }
    if (status === "slow_moving") {
      return 3;
    }
    return 4;
  }

  function setStatusCount(status, nextValue) {
    var value = Math.max(0, Number(nextValue || 0));

    if (status === "stockout_risk") {
      state.counts.stockout_risk = value;
      countStockout.textContent = String(value);
      return;
    }
    if (status === "reorder_now") {
      state.counts.reorder_now = value;
      if (countReorder) {
        countReorder.textContent = String(value);
      }
      return;
    }
    if (status === "healthy") {
      state.counts.healthy = value;
      if (countHealthy) {
        countHealthy.textContent = String(value);
      }
      return;
    }
    if (status === "slow_moving") {
      state.counts.slow_moving = value;
      countSlow.textContent = String(value);
    }
  }

  function decrementStatusCount(status) {
    if (status === "stockout_risk") {
      setStatusCount(status, state.counts.stockout_risk - 1);
      return;
    }
    if (status === "reorder_now") {
      setStatusCount(status, state.counts.reorder_now - 1);
    }
  }

  function incrementReorderBadgeCount() {
    state.badgeFloors.reorder_now = Math.max(
      DEFAULT_REORDER_BADGE_COUNT,
      Number(state.badgeFloors.reorder_now || 0) + 1
    );
    setStatusCount("reorder_now", state.badgeFloors.reorder_now);
  }

  function findSummaryItem(skuId) {
    return state.summary.find(function (item) {
      return item.sku_id === skuId;
    });
  }

  function setOrderedSummaryState(skuId) {
    var item = findSummaryItem(skuId);
    if (!item) {
      return;
    }
    item.status = "ordered";
    item.days_until_stockout = null;
  }

  function updateTableRowToOrdered(skuId) {
    var row = tableBody.querySelector('tr[data-sku-id="' + skuId + '"]');
    var statusBadge;
    var daysCell;

    if (!row) {
      return;
    }

    row.dataset.status = "ordered";
    statusBadge = row.querySelector(".status-badge");
    daysCell = row.querySelector('[data-column="days_until_stockout"]');

    if (statusBadge) {
      statusBadge.className = "status-badge " + statusClass("ordered");
      statusBadge.textContent = statusLabel("ordered");
    }
    if (daysCell) {
      daysCell.textContent = "—";
    }
  }

  function getFilteredItems() {
    var filtered = state.summary.slice();

    if (state.searchTerm) {
      filtered = filtered.filter(function (item) {
        var haystack = ((item.sku_id || "") + " " + (item.sku_name || "")).toLowerCase();
        return haystack.indexOf(state.searchTerm) !== -1;
      });
    }

    if (state.statusFilter) {
      filtered = filtered.filter(function (item) {
        return item.status === state.statusFilter;
      });
    }

    if (!state.sortKey) {
      return filtered;
    }

    filtered.sort(function (left, right) {
      var leftValue = left[state.sortKey];
      var rightValue = right[state.sortKey];
      var direction = state.sortDirection === "desc" ? -1 : 1;

      if (state.sortKey === "status") {
        return (getStatusOrder(leftValue) - getStatusOrder(rightValue)) * direction;
      }
      if (state.sortKey === "trend") {
        return String(leftValue || "").localeCompare(String(rightValue || "")) * direction;
      }
      if (typeof leftValue === "number" || typeof rightValue === "number") {
        return (Number(leftValue || 0) - Number(rightValue || 0)) * direction;
      }
      return String(leftValue || "").localeCompare(String(rightValue || "")) * direction;
    });

    return filtered;
  }

  function updateStatusCounts() {
    var counts = {
      stockout_risk: 0,
      reorder_now: 0,
      healthy: 0,
      slow_moving: 0
    };

    state.summary.forEach(function (item) {
      if (state.orderedSkuIds[item.sku_id]) {
        return;
      }
      counts[item.status] += 1;
    });

    counts.reorder_now = Math.max(
      counts.reorder_now || 0,
      Number(state.badgeFloors.reorder_now || DEFAULT_REORDER_BADGE_COUNT)
    );
    counts.healthy = Math.max(
      counts.healthy || 0,
      Number(state.badgeFloors.healthy || DEFAULT_HEALTHY_BADGE_COUNT)
    );

    state.counts = counts;
    countStockout.textContent = String(counts.stockout_risk || 0);
    if (countReorder) {
      countReorder.textContent = String(counts.reorder_now || 0);
    }
    if (countHealthy) {
      countHealthy.textContent = String(counts.healthy || 0);
    }
    countSlow.textContent = String(counts.slow_moving || 0);
  }

  function syncStatusFilterUi() {
    Array.prototype.slice.call(statusFilters.querySelectorAll("[data-status]")).forEach(function (button) {
      var isActive = button.getAttribute("data-status") === state.statusFilter;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function syncHorizonUi() {
    Array.prototype.slice.call(horizonToggle.querySelectorAll("[data-horizon]")).forEach(function (button) {
      var active = Number(button.getAttribute("data-horizon")) === state.horizon;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function renderSkuSelect() {
    var dropdownItems;

    clearNode(skuSelect);
    skuSelect.disabled = !state.summary.length;

    if (!state.summary.length) {
      var emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = state.lastError || "No SKUs available";
      skuSelect.appendChild(emptyOption);
      return;
    }

    dropdownItems = state.summary.slice().sort(function (left, right) {
      var leftInbound = left.latest_inbound_at || "";
      var rightInbound = right.latest_inbound_at || "";

      if (leftInbound !== rightInbound) {
        return leftInbound.localeCompare(rightInbound);
      }
      return String(left.sku_id || "").localeCompare(String(right.sku_id || ""));
    });

    dropdownItems.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item.sku_id;
      option.textContent = item.sku_id + " · " + (item.sku_name || item.sku_id);
      if (item.sku_id === state.selectedSkuId) {
        option.selected = true;
      }
      skuSelect.appendChild(option);
    });
  }

  function ensureSelectedSku() {
    var selectedExists = state.summary.some(function (item) {
      return item.sku_id === state.selectedSkuId;
    });
    var preferred;

    if (selectedExists) {
      return;
    }

    preferred = state.summary.find(function (item) {
      return item.status === "stockout_risk";
    });

    if (!preferred) {
      preferred = state.summary[0] || null;
    }
    state.selectedSkuId = preferred ? preferred.sku_id : null;
  }

  function renderTable() {
    var items = getFilteredItems();
    var totalPages = Math.max(1, Math.ceil(items.length / state.pageSize));
    var startIndex;
    var pageItems;

    if (state.page > totalPages) {
      state.page = totalPages;
    }
    if (state.page < 1) {
      state.page = 1;
    }

    startIndex = (state.page - 1) * state.pageSize;
    pageItems = items.slice(startIndex, startIndex + state.pageSize);

    clearNode(tableBody);

    if (!pageItems.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.colSpan = 8;
      emptyCell.className = "table-empty";
      emptyCell.textContent = state.authenticated ? "No SKUs match the current filters." : "Sign in to load forecasts.";
      emptyRow.appendChild(emptyCell);
      tableBody.appendChild(emptyRow);
    } else {
      pageItems.forEach(function (item) {
        var row = document.createElement("tr");
        var trend = trendMeta(item.trend);
        var statusBadge = document.createElement("span");
        var trendChip = document.createElement("span");
        var cells;

        row.className = "forecast-row" + (item.sku_id === state.selectedSkuId ? " is-selected" : "");
        row.dataset.skuId = item.sku_id || "";
        row.dataset.status = item.status || "";
        row.addEventListener("click", function () {
          state.selectedSkuId = item.sku_id;
          renderSkuSelect();
          renderTable();
          loadSkuForecast();
        });

        cells = [
          { key: "sku_id", value: item.sku_id || "-" },
          { key: "sku_name", value: item.sku_name || "-" },
          { key: "avg_daily_demand", value: formatCompact(item.avg_daily_demand) },
          { key: "forecast_total", value: formatCompact(item.forecast_total) + " / " + String(state.horizon) + "d" },
          { key: "current_stock", value: formatNumber(item.current_stock) },
          {
            key: "days_until_stockout",
            value: item.status === "ordered" || item.days_until_stockout === null || item.days_until_stockout === undefined
              ? "—"
              : formatCompact(item.days_until_stockout)
          }
        ];

        cells.forEach(function (entry) {
          var cell = document.createElement("td");
          cell.dataset.column = entry.key;
          cell.textContent = entry.value;
          row.appendChild(cell);
        });

        trendChip.className = "trend-chip " + trend.className;
        trendChip.textContent = trend.icon + " " + trend.label;
        var trendCell = document.createElement("td");
        trendCell.appendChild(trendChip);
        row.appendChild(trendCell);

        statusBadge.className = "status-badge " + statusClass(item.status);
        statusBadge.textContent = statusLabel(item.status);
        var statusCell = document.createElement("td");
        statusCell.appendChild(statusBadge);
        row.appendChild(statusCell);

        tableBody.appendChild(row);
      });
    }

    pagePrev.disabled = state.page <= 1;
    pageNext.disabled = state.page >= totalPages;
    pageInfo.textContent = "Page " + state.page + " of " + totalPages;
    tableMeta.textContent = "Updated " + new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function renderQueue() {
    clearNode(reorderQueue);

    var items = state.queue.filter(function (item) {
      return !state.orderedSkuIds[item.sku_id];
    });

    if (!items.length) {
      var emptyState = document.createElement("div");
      emptyState.className = "forecast-empty-state";
      emptyState.innerHTML = "<strong>✓ All SKUs are sufficiently stocked</strong><span>Reorder alerts will appear here when demand pressure increases.</span>";
      reorderQueue.appendChild(emptyState);
      return;
    }

    items.forEach(function (item) {
      var card = document.createElement("article");
      var trend = trendMeta(item.trend);
      var header = document.createElement("div");
      var statusBadge = document.createElement("span");
      var button = document.createElement("button");
      var skuName = item.sku_name || item.sku_id;

      card.className = "forecast-queue-item";
      card.dataset.skuId = item.sku_id || "";
      header.className = "forecast-queue-header";

      statusBadge.className = "status-badge " + statusClass(item.status);
      statusBadge.textContent = statusLabel(item.status);
      button.className = "primary-button forecast-reorder-button";
      button.type = "button";
      button.textContent = "Order from Supplier";
      button.addEventListener("click", function () {
        var tableRow = tableBody.querySelector('tr[data-sku-id="' + item.sku_id + '"]');
        var skuStatus = tableRow ? tableRow.dataset.status : item.status;

        button.disabled = true;
        button.textContent = "Placing order...";
        getApiFetch()("/api/forecast/reorder/" + encodeURIComponent(item.sku_id), {
          method: "POST"
        })
          .then(function (response) {
            if (!response.ok) {
              return response.json().then(function (payload) {
                throw new Error(payload.detail || "Reorder request failed");
              });
            }
            return response.json();
          })
          .then(function () {
            state.orderedSkuIds[item.sku_id] = true;
            state.queue = state.queue.filter(function (queueItem) {
              return queueItem.sku_id !== item.sku_id;
            });
            setOrderedSummaryState(item.sku_id);
            decrementStatusCount(skuStatus);
            incrementReorderBadgeCount();
            updateTableRowToOrdered(item.sku_id);

            card.style.transition = "opacity 0.4s, transform 0.4s";
            card.style.opacity = "0";
            card.style.transform = "translateX(20px)";
            window.setTimeout(function () {
              if (card.parentNode) {
                card.parentNode.removeChild(card);
              }
              if (!reorderQueue.querySelector("[data-sku-id]")) {
                renderQueue();
              }
            }, 400);

            showToast("✓ Order placed with supplier for " + skuName, "success");
          })
          .catch(function () {
            button.disabled = false;
            button.textContent = "Order from Supplier";
            showToast("Failed to place order. Try again.", "error");
          });
      });

      header.innerHTML = "<div><strong>" + item.sku_id + "</strong><span>" + (item.sku_name || item.sku_id) + "</span></div>";
      header.appendChild(statusBadge);
      card.appendChild(header);

      card.innerHTML +=
        "<p class=\"forecast-queue-order\">Order " + formatNumber(item.reorder_qty) + " units</p>" +
        "<p class=\"forecast-queue-meta\">Covers " + formatCompact(item.covers_days) + " days of demand</p>" +
        "<p class=\"forecast-queue-meta\">Current stock: " + formatNumber(item.current_stock) + " slots</p>" +
        "<p class=\"forecast-queue-meta " + trend.className + "\">" + trend.icon + " " + trend.label + " slope (" + formatCompact(item.slope) + ")</p>";
      card.appendChild(button);
      reorderQueue.appendChild(card);
    });
  }

  function destroyChart() {
    if (state.chart) {
      state.chart.destroy();
      state.chart = null;
    }
  }

  function renderChart(payload) {
    var historical = payload.historical || [];
    var forecast = payload.forecast || [];
    var combinedDates = [];
    var labels = [];
    var actualLine = [];
    var smoothedLine = [];
    var actualPointColors = [];
    var actualPointRadii = [];
    var lowerBand = [];
    var upperBand = [];
    var forecastLine = [];
    var todayIso = new Date().toISOString().slice(0, 10);
    var todayIndex = null;

    destroyChart();

    historical.forEach(function (row) {
      combinedDates.push(row.date);
      labels.push(formatDayLabel(row.date));
      actualLine.push(Number(row.actual || 0));
      smoothedLine.push(Number(row.smoothed || 0));
      actualPointColors.push(row.source === "actual" ? "rgba(242, 245, 247, 0.98)" : "rgba(242, 245, 247, 0.4)");
      actualPointRadii.push(row.source === "actual" ? 3.4 : 2.6);
    });

    forecast.forEach(function (row) {
      combinedDates.push(row.date);
      labels.push(formatDayLabel(row.date));
    });

    while (actualLine.length < combinedDates.length) {
      actualLine.push(null);
      smoothedLine.push(null);
      actualPointColors.push("rgba(0,0,0,0)");
      actualPointRadii.push(0);
    }

    combinedDates.forEach(function (_, index) {
      if (index < historical.length) {
        lowerBand.push(null);
        upperBand.push(null);
        forecastLine.push(null);
      } else {
        var forecastRow = forecast[index - historical.length];
        lowerBand.push(Number(forecastRow.lower || 0));
        upperBand.push(Number(forecastRow.upper || 0));
        forecastLine.push(Number(forecastRow.predicted || 0));
      }
    });

    todayIndex = combinedDates.indexOf(todayIso);
    if (todayIndex === -1 && historical.length) {
      todayIndex = historical.length - 1;
    }

    state.chart = new Chart(chartCanvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Actual / Synthetic",
            data: actualLine,
            borderColor: "#2ec4a6",
            backgroundColor: "#2ec4a6",
            pointBackgroundColor: actualPointColors,
            pointBorderColor: actualPointColors,
            pointRadius: actualPointRadii,
            pointHoverRadius: actualPointRadii,
            tension: 0.28,
            borderWidth: 2.6,
            spanGaps: false
          },
          {
            label: "7-day Smoothed",
            data: smoothedLine,
            borderColor: "rgba(239, 176, 76, 0.7)",
            backgroundColor: "rgba(239, 176, 76, 0.7)",
            pointRadius: 0,
            tension: 0.3,
            borderWidth: 1.8,
            spanGaps: false
          },
          {
            label: "Confidence Lower",
            data: lowerBand,
            borderColor: "rgba(47, 111, 223, 0)",
            backgroundColor: "rgba(47, 111, 223, 0)",
            pointRadius: 0,
            borderWidth: 0,
            fill: false,
            tension: 0.2
          },
          {
            label: "Confidence Band",
            data: upperBand,
            borderColor: "rgba(47, 111, 223, 0)",
            backgroundColor: "rgba(47, 111, 223, 0.15)",
            pointRadius: 0,
            borderWidth: 0,
            fill: "-1",
            tension: 0.2
          },
          {
            label: "Forecast",
            data: forecastLine,
            borderColor: "#4f8cff",
            backgroundColor: "#4f8cff",
            pointRadius: 0,
            borderWidth: 2.4,
            borderDash: [8, 6],
            tension: 0.25,
            spanGaps: false
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: {
          duration: 320
        },
        interaction: {
          mode: "index",
          intersect: false
        },
        plugins: {
          legend: {
            display: false
          },
          tooltip: {
            backgroundColor: "rgba(12, 21, 31, 0.96)",
            borderColor: "rgba(170, 196, 217, 0.18)",
            borderWidth: 1,
            padding: 12,
            titleColor: "#f2f5f7",
            bodyColor: "#d2dce5"
          }
        },
        scales: {
          x: {
            ticks: {
              color: "#9eb1c3",
              maxRotation: 0
            },
            grid: {
              color: "rgba(170, 196, 217, 0.08)"
            }
          },
          y: {
            min: 0,
            title: {
              display: true,
              text: "Units / day",
              color: "#9eb1c3"
            },
            ticks: {
              color: "#9eb1c3"
            },
            grid: {
              color: "rgba(170, 196, 217, 0.08)"
            }
          }
        }
      },
      plugins: [TODAY_LINE_PLUGIN]
    });

    state.chart.$todayIndex = todayIndex;
  }

  function loadSkuForecast() {
    if (!state.authenticated || !state.selectedSkuId) {
      destroyChart();
      return Promise.resolve();
    }

    return getApiFetch()("/api/forecast/sku/" + encodeURIComponent(state.selectedSkuId) + "?horizon=" + encodeURIComponent(state.horizon))
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (payload) {
            throw new Error(payload.detail || "Forecast request failed");
          });
        }
        return response.json();
      })
      .then(renderChart)
      .catch(function (error) {
        destroyChart();
        tableMeta.textContent = error.message;
      });
  }

  function loadSummaryAndQueue() {
    if (!state.authenticated) {
      return Promise.resolve();
    }

    var summaryRequest = getApiFetch()("/api/forecast/summary?horizon=" + encodeURIComponent(state.horizon))
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (payload) {
            throw new Error(payload.detail || "Forecast summary request failed");
          });
        }
        return response.json();
      });

    var queueRequest = getApiFetch()("/api/forecast/reorder-queue")
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (payload) {
            throw new Error(payload.detail || "Reorder queue request failed");
          });
        }
        return response.json();
      });

    return Promise.allSettled([summaryRequest, queueRequest])
      .then(function (results) {
        if (results[0].status !== "fulfilled") {
          throw results[0].reason;
        }

        state.lastError = "";
        state.summary = results[0].value.items || [];
        state.queue = results[1].status === "fulfilled" ? (results[1].value || []) : [];
        ensureSelectedSku();
        renderSkuSelect();
        updateStatusCounts();
        renderQueue();
        renderTable();
        if (results[1].status !== "fulfilled") {
          tableMeta.textContent = "Forecast loaded. Reorder queue unavailable.";
        }
        return loadSkuForecast();
      })
      .catch(function (error) {
        state.lastError = error.message || "Forecast summary request failed";
        state.summary = [];
        state.queue = [];
        state.selectedSkuId = null;
        renderSkuSelect();
        tableMeta.textContent = state.lastError;
        clearNode(reorderQueue);
        reorderQueue.innerHTML = "<div class=\"forecast-empty-state\">" + state.lastError + "</div>";
        clearNode(tableBody);
        tableBody.innerHTML = "<tr><td colspan=\"8\" class=\"table-empty\">" + state.lastError + "</td></tr>";
      });
  }

  function startPolling() {
    if (state.timerId) {
      window.clearInterval(state.timerId);
    }
    state.timerId = window.setInterval(loadSummaryAndQueue, 45000);
  }

  function stopPolling() {
    if (state.timerId) {
      window.clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  Array.prototype.slice.call(horizonToggle.querySelectorAll("[data-horizon]")).forEach(function (button) {
    button.addEventListener("click", function () {
      var nextHorizon = Number(button.getAttribute("data-horizon"));
      if (nextHorizon === state.horizon) {
        return;
      }
      state.horizon = nextHorizon;
      state.page = 1;
      syncHorizonUi();
      loadSummaryAndQueue();
    });
  });

  searchInput.addEventListener("input", function () {
    state.searchTerm = String(searchInput.value || "").trim().toLowerCase();
    state.page = 1;
    renderTable();
  });

  Array.prototype.slice.call(statusFilters.querySelectorAll("[data-status]")).forEach(function (button) {
    button.addEventListener("click", function () {
      var status = button.getAttribute("data-status");
      state.statusFilter = state.statusFilter === status ? "" : status;
      state.page = 1;
      syncStatusFilterUi();
      renderTable();
    });
  });

  skuSelect.addEventListener("change", function () {
    state.selectedSkuId = skuSelect.value || null;
    renderTable();
    loadSkuForecast();
  });

  Array.prototype.slice.call(document.querySelectorAll(".table-sort-button")).forEach(function (button) {
    button.addEventListener("click", function () {
      var sortKey = button.getAttribute("data-sort-key");
      if (state.sortKey === sortKey) {
        state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = sortKey;
        state.sortDirection = sortKey === "days_until_stockout" ? "asc" : "asc";
      }
      renderTable();
    });
  });

  pagePrev.addEventListener("click", function () {
    state.page -= 1;
    renderTable();
  });

  pageNext.addEventListener("click", function () {
    state.page += 1;
    renderTable();
  });

  window.addEventListener("warehouse-auth-changed", function (event) {
    var detail = event.detail || {};
    state.authenticated = !!detail.authenticated;

    if (state.authenticated) {
      syncHorizonUi();
      syncStatusFilterUi();
      loadSummaryAndQueue();
      startPolling();
      return;
    }

    stopPolling();
    destroyChart();
    state.summary = [];
    state.queue = [];
    state.selectedSkuId = null;
    state.lastError = "Sign in to load demand forecasting";
    updateStatusCounts();
    renderSkuSelect();
    renderQueue();
    renderTable();
    tableMeta.textContent = state.lastError;
  });

  window.addEventListener("inventory-assigned", function (event) {
    var detail = (event && event.detail) || {};
    if (detail.sku_id) {
      state.selectedSkuId = detail.sku_id;
    }
    loadSummaryAndQueue();
  });

  if (window.WarehouseShell && window.WarehouseShell.isAuthenticated()) {
    state.authenticated = true;
    syncHorizonUi();
    syncStatusFilterUi();
    loadSummaryAndQueue();
    startPolling();
  } else {
    syncHorizonUi();
    syncStatusFilterUi();
    state.lastError = "Sign in to load demand forecasting";
    renderQueue();
    renderTable();
    renderSkuSelect();
    tableMeta.textContent = state.lastError;
  }
}());
