(function () {
  const COLOR_MAP = {
    empty: "#21262d",
    occupied: "#388bfd",
    congested: "#f85149",
    forklift: "#e3b341"
  };
  var loginMetricsFallback = window.__WAREVISION_LOGIN_METRICS_FALLBACK__ || null;

  var loginShell = document.getElementById("login-shell");
  var appShell = document.getElementById("app-shell");
  var loginForm = document.getElementById("login-form");
  var loginUsername = document.getElementById("login-username");
  var loginPassword = document.getElementById("login-password");
  var loginButton = document.getElementById("login-button");
  var loginError = document.getElementById("login-error");
  var loginStatTotalSlots = document.getElementById("login-stat-total-slots");
  var loginStatFastPick = document.getElementById("login-stat-fast-pick");
  var loginStatQueueSavings = document.getElementById("login-stat-queue-savings");
  var loginLiveStatus = document.getElementById("login-live-status");
  var logoutButton = document.getElementById("logout-button");
  var operatorName = document.getElementById("operator-name");
  var navAnalytics = document.getElementById("nav-analytics");
  var navUpload = document.getElementById("nav-upload");
  var navMap = document.getElementById("nav-map");
  var navForecast = document.getElementById("nav-forecast");
  var analyticsView = document.getElementById("view-analytics");
  var liveMapView = document.getElementById("view-live-map");
  var inventoryUploadView = document.getElementById("view-inventory-upload");
  var forecastView = document.getElementById("view-forecast");

  var warehouseMap = document.getElementById("warehouse-map");
  var tooltip = document.getElementById("tooltip");
  var heatmapToggle = document.getElementById("heatmap-toggle");
  var heatmapLegend = document.getElementById("heatmap-legend");
  var liveFeedText = document.getElementById("live-feed-text");

  var panelTitle = document.getElementById("panel-title");
  var panelSubtitle = document.getElementById("panel-subtitle");
  var statusText = document.getElementById("status-text");
  var factSlot = document.getElementById("fact-slot");
  var factSku = document.getElementById("fact-sku");
  var factQty = document.getElementById("fact-qty");
  var factPicks = document.getElementById("fact-picks");
  var recommendationCard = document.getElementById("recommendation-card");

  var metricOccupancy = document.getElementById("metric-occupancy");
  var metricQueue = document.getElementById("metric-queue");
  var metricAssets = document.getElementById("metric-assets");
  var metricUpdated = document.getElementById("metric-updated");
  var mapZoneCount = document.getElementById("map-zone-count");
  var mapSlotCount = document.getElementById("map-slot-count");
  var mapBusyCount = document.getElementById("map-busy-count");
  var mapSavings = document.getElementById("map-savings");
  var legendEmpty = document.querySelector(".legend .dot.empty");
  var legendOccupied = document.querySelector(".legend .dot.occupied");
  var legendCongested = document.querySelector(".legend .dot.congested");
  var legendAsset = document.querySelector(".legend .dot.asset");

  var state = {
    authenticated: false,
    username: null,
    zones: [],
    slots: [],
    assets: [],
    heatmapZones: {},
    heatmapEnabled: false,
    hoveredSlot: null,
    selectedSlot: null,
    pendingSelectedSlotId: null,
    floorLoadedAt: null,
    assetsLoadedAt: null,
    queueCount: 0,
    queueSavings: 0,
    slotOverrides: {},
    floorTimerId: null,
    assetsTimerId: null,
    loginMetricsTimerId: null,
    activeView: "analytics"
  };

  if (legendEmpty) {
    legendEmpty.style.backgroundColor = COLOR_MAP.empty;
  }
  if (legendOccupied) {
    legendOccupied.style.backgroundColor = COLOR_MAP.occupied;
  }
  if (legendCongested) {
    legendCongested.style.backgroundColor = COLOR_MAP.congested;
  }
  if (legendAsset) {
    legendAsset.style.backgroundColor = COLOR_MAP.forklift;
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function normalizeNumber(value) {
    if (value === null || value === undefined || value === "") {
      return 0;
    }
    return Number(value);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function zoneKey(zone) {
    var name = String(zone.zone_name || "").toUpperCase();
    var type = String(zone.zone_type || "").toUpperCase();
    if (name.indexOf("RECEIV") !== -1 || type.indexOf("RECEIV") !== -1) {
      return "receiving";
    }
    if (name.indexOf("FAST") !== -1 || type.indexOf("FAST") !== -1) {
      return "fastpick";
    }
    if (name.indexOf("BULK") !== -1 || type.indexOf("BULK") !== -1 || type.indexOf("STORE") !== -1) {
      return "bulk";
    }
    if (name.indexOf("DISPATCH") !== -1 || type.indexOf("DISPATCH") !== -1) {
      return "dispatch";
    }
    return "bulk";
  }

  function zoneAccent(zone) {
    if (zoneKey(zone) === "receiving") {
      return "#2dd4bf";
    }
    if (zoneKey(zone) === "fastpick") {
      return "#2ea043";
    }
    if (zoneKey(zone) === "dispatch") {
      return "#a371f7";
    }
    return "#388bfd";
  }

  function zoneOccupiedClass(zone) {
    return "is-occupied-bulk";
  }

  function slotHeatOpacity(slot) {
    return 0.55 + (clamp(normalizeNumber(slot.pick_count) / 80, 0, 1) * 0.25);
  }

  function slotShortLabel(slot) {
    var slotId = String(slot.slot_id || "");
    var parts = slotId.split("-");
    var aisle = parts.length > 2 ? parts[1] : "";
    var bay = parts.length > 1 ? parts[parts.length - 1] : slotId;

    if (aisle && bay) {
      return aisle.replace(/^A/, "") + "-" + bay;
    }
    return slotId.slice(-5);
  }

  function slotSortValue(slot) {
    var aisle = String(slot.aisle || "").replace(/\D/g, "");
    var bay = String(slot.bay || "").replace(/\D/g, "");
    var level = String(slot.level || "").replace(/\D/g, "");
    return (
      String(aisle).padStart(4, "0") +
      String(bay).padStart(4, "0") +
      String(level).padStart(4, "0") +
      String(slot.slot_id || "")
    );
  }

  function slotAisleLabel(slot) {
    var aisle = String(slot.aisle || "").replace(/^A/i, "");
    if (aisle) {
      return aisle;
    }
    var parts = String(slot.slot_id || "").split("-");
    if (parts.length > 1) {
      return String(parts[1] || "").replace(/^A/i, "");
    }
    return "--";
  }

  function applySlotColor(slotNode, zone, slot) {
    var isOccupied = slot.is_occupied || slot.quantity > 0 || slot.sku_id;
    var color = COLOR_MAP.occupied;

    if (!isOccupied) {
      slotNode.style.backgroundColor = COLOR_MAP.empty;
      slotNode.style.borderColor = "#30363d";
      return;
    }

    if (normalizeNumber(slot.pick_count) > 50) {
      color = COLOR_MAP.congested;
    }

    slotNode.style.backgroundColor = color;
    slotNode.style.borderColor = color;
  }

  function setStatus(message) {
    statusText.textContent = message;
    liveFeedText.textContent = [
      "Live warehouse feed active",
      message || "Monitoring floor activity",
      state.zones.length ? state.zones.length + " zones online" : "zone telemetry pending",
      state.slots.length ? state.slots.length + " slots tracked" : "slot telemetry pending",
      state.assets.length ? state.assets.length + " workers visible" : "worker telemetry pending",
      state.queueCount ? state.queueCount + " queue items pending" : "slotting queue stable"
    ].join("   •   ");
  }

  function setLoginError(message) {
    if (!message) {
      loginError.textContent = "";
      loginError.classList.add("hidden");
      return;
    }
    loginError.textContent = message;
    loginError.classList.remove("hidden");
  }

  function dispatchAuthChanged() {
    window.dispatchEvent(
      new CustomEvent("warehouse-auth-changed", {
        detail: {
          authenticated: state.authenticated,
          username: state.username
        }
      })
    );
  }

  function showAuthenticatedView() {
    stopLoginMetricsPolling();
    loginShell.classList.add("hidden");
    appShell.classList.remove("hidden");
    operatorName.textContent = state.username || "-";
  }

  function showLoggedOutView() {
    loginShell.classList.remove("hidden");
    appShell.classList.add("hidden");
    operatorName.textContent = "-";
    setActiveView("analytics");
    state.selectedSlot = null;
    state.hoveredSlot = null;
    state.pendingSelectedSlotId = null;
    state.zones = [];
    state.slots = [];
    state.assets = [];
    state.heatmapZones = {};
    state.floorLoadedAt = null;
    state.assetsLoadedAt = null;
    state.queueCount = 0;
    state.queueSavings = 0;
    updatePanel(null);
    updateMetrics();
    renderMap();
    setStatus("Sign in to load the floor map.");
    startLoginMetricsPolling();
  }

  function handleUnauthorized() {
    state.authenticated = false;
    state.username = null;
    dispatchAuthChanged();
    showLoggedOutView();
  }

  function apiFetch(url, options) {
    var requestOptions = options || {};
    var nextOptions = {};
    Object.keys(requestOptions).forEach(function (key) {
      nextOptions[key] = requestOptions[key];
    });
    nextOptions.credentials = "include";

    return fetch(url, nextOptions).then(function (response) {
      if (response.status === 401) {
        handleUnauthorized();
      }
      return response;
    });
  }

  window.warehouseFetch = apiFetch;
  window.WarehouseShell = {
    isAuthenticated: function () {
      return state.authenticated;
    },
    setActiveView: function (viewName) {
      if (!state.authenticated && viewName === "upload") {
        return;
      }
      setActiveView(viewName);
    },
    refreshFloor: function () {
      return loadFloor().then(function () {
        if (state.heatmapEnabled) {
          return loadHeatmap();
        }
        return Promise.resolve();
      });
    },
    getFloorSnapshot: function () {
      return {
        zones: state.zones.slice(),
        slots: state.slots.slice(),
        loadedAt: state.floorLoadedAt
      };
    }
  };

  function setActiveView(viewName) {
    var showAnalytics = viewName === "analytics";
    var showUpload = viewName === "upload";
    var showForecast = viewName === "forecast";

    state.activeView = showAnalytics ? "analytics" : (showUpload ? "upload" : (showForecast ? "forecast" : "map"));
    analyticsView.classList.toggle("hidden", !showAnalytics);
    analyticsView.classList.toggle("is-active", showAnalytics);
    inventoryUploadView.classList.toggle("hidden", !showUpload);
    inventoryUploadView.classList.toggle("is-active", showUpload);
    forecastView.classList.toggle("hidden", !showForecast);
    forecastView.classList.toggle("is-active", showForecast);
    liveMapView.classList.toggle("hidden", showAnalytics || showUpload || showForecast);
    liveMapView.classList.toggle("is-active", !showAnalytics && !showUpload && !showForecast);
    navAnalytics.classList.toggle("is-active", showAnalytics);
    navUpload.classList.toggle("is-active", showUpload);
    navForecast.classList.toggle("is-active", showForecast);
    navMap.classList.toggle("is-active", !showAnalytics && !showUpload && !showForecast);
    navAnalytics.setAttribute("aria-pressed", showAnalytics ? "true" : "false");
    navUpload.setAttribute("aria-pressed", showUpload ? "true" : "false");
    navForecast.setAttribute("aria-pressed", showForecast ? "true" : "false");
    navMap.setAttribute("aria-pressed", !showAnalytics && !showUpload && !showForecast ? "true" : "false");
  }

  function emitFloorUpdated() {
    window.dispatchEvent(
      new CustomEvent("warehouse-floor-updated", {
        detail: {
          zones: state.zones.slice(),
          slots: state.slots.slice(),
          loadedAt: state.floorLoadedAt
        }
      })
    );
  }

  function findSlotById(slotId) {
    var index;
    if (!slotId) {
      return null;
    }
    for (index = 0; index < state.slots.length; index += 1) {
      if (state.slots[index].slot_id === slotId) {
        return state.slots[index];
      }
    }
    return null;
  }

  function syncSelectedSlot() {
    var targetSlotId = state.pendingSelectedSlotId;
    if (!targetSlotId && state.selectedSlot) {
      targetSlotId = state.selectedSlot.slot_id;
    }
    state.pendingSelectedSlotId = null;
    state.selectedSlot = findSlotById(targetSlotId);
    updatePanel(state.selectedSlot);
  }

  function formatRelativeTimestamp(dateValue) {
    if (!dateValue) {
      return "-";
    }
    return dateValue.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function formatMetersCompact(value) {
    return Number(value || 0).toFixed(1) + "m";
  }

  function formatPercent(value) {
    return Number(value || 0).toFixed(1) + "%";
  }

  function formatMetersDisplay(value) {
    return (Number(value || 0) / 1000).toFixed(1) + "km";
  }

  function loginButtonMarkup(label) {
    return (
      "<span>" + label + "</span>" +
      "<span class=\"auth-submit-icon\" aria-hidden=\"true\">" +
      "<svg viewBox=\"0 0 20 20\" fill=\"none\" role=\"presentation\" focusable=\"false\">" +
      "<path d=\"M4.5 10H15.5\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\"></path>" +
      "<path d=\"M10.5 5L15.5 10L10.5 15\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"></path>" +
      "</svg>" +
      "</span>"
    );
  }

  function updateLoginMetrics(metrics) {
    var safeMetrics = metrics || loginMetricsFallback;
    var totalSlots = safeMetrics && safeMetrics.total_slots !== undefined ? safeMetrics.total_slots : "--";
    var fastPick = safeMetrics ? formatPercent(safeMetrics.fast_pick_utilization_pct) : "--";
    var queueSavings = safeMetrics ? formatMetersDisplay(safeMetrics.queue_savings_m) : "--";
    var zonesOnline = safeMetrics && safeMetrics.zones_online !== undefined ? safeMetrics.zones_online : "--";

    if (loginStatTotalSlots) {
      loginStatTotalSlots.textContent = String(totalSlots);
    }
    if (loginStatFastPick) {
      loginStatFastPick.textContent = fastPick;
    }
    if (loginStatQueueSavings) {
      loginStatQueueSavings.textContent = queueSavings;
    }
    if (loginLiveStatus) {
      loginLiveStatus.textContent =
        "Live warehouse feed active \u00b7 " + String(zonesOnline) + " zones online";
    }
  }

  function updateMetrics() {
    var occupied = 0;
    var latestTimestamp = null;

    state.slots.forEach(function (slot) {
      if (slot.is_occupied || slot.quantity > 0 || slot.sku_id) {
        occupied += 1;
      }
    });

    if (state.floorLoadedAt && state.assetsLoadedAt) {
      latestTimestamp = state.floorLoadedAt > state.assetsLoadedAt ? state.floorLoadedAt : state.assetsLoadedAt;
    } else {
      latestTimestamp = state.floorLoadedAt || state.assetsLoadedAt;
    }

    metricOccupancy.textContent = state.slots.length ? occupied + " / " + state.slots.length : "-";
    metricQueue.textContent = state.authenticated ? String(state.queueCount) : "-";
    metricAssets.textContent = state.authenticated ? String(state.assets.length) : "-";
    metricUpdated.textContent = formatRelativeTimestamp(latestTimestamp);
    mapZoneCount.textContent = state.authenticated ? String(state.zones.length) : "-";
    mapSlotCount.textContent = state.authenticated ? String(state.slots.length) : "-";
    mapBusyCount.textContent = state.authenticated ? String(occupied) : "-";
    mapSavings.textContent = state.authenticated ? formatMetersCompact(state.queueSavings) : "-";
  }

  function cloneSlot(slot, zone) {
    var next = {};
    Object.keys(slot).forEach(function (key) {
      next[key] = slot[key];
    });
    next.x = normalizeNumber(next.x);
    next.y = normalizeNumber(next.y);
    next.width = normalizeNumber(next.width);
    next.height = normalizeNumber(next.height);
    next.pick_count = normalizeNumber(next.pick_count);
    next.quantity = normalizeNumber(next.quantity);
    next.is_occupied = normalizeNumber(next.is_occupied);
    next.zone_name = zone.zone_name;
    next.zone_type = zone.zone_type;
    next.zone_id = zone.zone_id;
    return next;
  }

  function slotMatchesOverride(slot, override) {
    var keys = Object.keys(override);
    var index;
    for (index = 0; index < keys.length; index += 1) {
      if (slot[keys[index]] !== override[keys[index]]) {
        return false;
      }
    }
    return true;
  }

  function applyOverride(slot) {
    var override = state.slotOverrides[slot.slot_id];
    if (!override) {
      return slot;
    }
    if (slotMatchesOverride(slot, override)) {
      delete state.slotOverrides[slot.slot_id];
      return slot;
    }
    return Object.assign({}, slot, override);
  }

  function updateSlotInState(slotId, patch) {
    var updated = null;

    state.slots = state.slots.map(function (slot) {
      if (slot.slot_id !== slotId) {
        return slot;
      }
      updated = Object.assign({}, slot, patch);
      return updated;
    });

    state.zones = state.zones.map(function (zone) {
      var nextZone = Object.assign({}, zone);
      var changed = false;
      nextZone.slots = (zone.slots || []).map(function (slot) {
        if (slot.slot_id !== slotId) {
          return slot;
        }
        changed = true;
        return Object.assign({}, slot, patch);
      });
      return changed ? nextZone : zone;
    });

    if (updated) {
      state.slotOverrides[slotId] = patch;
    }
    return updated;
  }

  function handleRecommendationAccepted(detail) {
    var sourceSlot = findSlotById(detail.from_slot);
    var destinationSlot = findSlotById(detail.to_slot);
    var movedData;

    if (!sourceSlot || !destinationSlot) {
      return loadFloor();
    }

    movedData = {
      sku_id: sourceSlot.sku_id || detail.sku_id || null,
      sku_name: sourceSlot.sku_name || detail.sku_name || null,
      quantity: sourceSlot.quantity || 0,
      pick_count: sourceSlot.pick_count || 0,
      is_occupied: 1,
      recommendation: null
    };

    updateSlotInState(detail.from_slot, {
      sku_id: null,
      sku_name: null,
      quantity: 0,
      pick_count: 0,
      waste_score: 0,
      is_occupied: 0,
      recommendation: null
    });

    updateSlotInState(detail.to_slot, movedData);

    state.pendingSelectedSlotId = detail.to_slot || null;
    syncSelectedSlot();
    updateMetrics();
    renderMap();
  }

  function updateTooltip(slotId, event) {
    var slot = findSlotById(slotId);
    var mapRect = warehouseMap.getBoundingClientRect();
    var isOccupied;
    if (!slot) {
      hideTooltip();
      return;
    }
    isOccupied = slot.is_occupied || slot.quantity > 0 || slot.sku_id;

    if (!isOccupied) {
      tooltip.innerHTML =
        "<div>Slot: " + (slot.slot_id || "-") + "</div>" +
        "<div>Status: Available</div>";
    } else {
      tooltip.innerHTML =
        "<div>Slot: " + (slot.slot_id || "-") + "</div>" +
        "<div>SKU: " + (slot.sku_id || "-") + "</div>" +
        "<div>Pick frequency: " + (slot.pick_count || 0) + "/30d</div>" +
        "<div>Zone: " + (slot.zone_name || "-") + "</div>";
    }
    tooltip.style.left = (event.clientX - mapRect.left) + "px";
    tooltip.style.top = (event.clientY - mapRect.top) + "px";
    tooltip.classList.remove("hidden");
  }

  function hideTooltip() {
    tooltip.classList.add("hidden");
  }

  function updatePanel(slot) {
    if (!slot) {
      panelTitle.textContent = "No slot selected";
      panelSubtitle.textContent = "Click an occupied slot to inspect inventory and recommendations.";
      factSlot.textContent = "-";
      factSku.textContent = "-";
      factQty.textContent = "-";
      factPicks.textContent = "-";
      recommendationCard.className = "recommendation empty-state";
      recommendationCard.textContent = "No recommendation for the selected slot.";
      return;
    }

    panelTitle.textContent = slot.slot_id;
    panelSubtitle.textContent = slot.zone_name + " · Bay " + (slot.bay || "-") + " · Level " + (slot.level || "-");
    factSlot.textContent = slot.slot_id;
    factSku.textContent = slot.sku_name || "Empty";
    factQty.textContent = String(slot.quantity || 0);
    factPicks.textContent = String(slot.pick_count || 0);

    if (slot.recommendation) {
      recommendationCard.className = "recommendation";
      recommendationCard.innerHTML =
        "<strong>Move to " + slot.recommendation.to_slot + "</strong>" +
        "<div>Status: " + (slot.recommendation.status || "PENDING") + "</div>" +
        "<div>Estimated saving: " + (slot.recommendation.saving_m || 0) + " m</div>" +
        "<div>" + (slot.recommendation.reason || "No AI rationale available.") + "</div>";
    } else {
      recommendationCard.className = "recommendation empty-state";
      recommendationCard.textContent = "No recommendation for the selected slot.";
    }
  }

  function buildWorkerLayer(zone) {
    var layer = document.createElement("div");
    var zx = normalizeNumber(zone.x1);
    var zy = normalizeNumber(zone.y1);
    var zw = Math.max(1, normalizeNumber(zone.x2) - zx);
    var zh = Math.max(1, normalizeNumber(zone.y2) - zy);

    layer.className = "zone-worker-layer";

    state.assets.forEach(function (asset) {
      if (asset.x < zx || asset.x > zx + zw || asset.y < zy || asset.y > zy + zh) {
        return;
      }

      var dot = document.createElement("span");
      dot.className = "worker-dot";
      dot.style.left = (((asset.x - zx) / zw) * 100) + "%";
      dot.style.top = (((asset.y - zy) / zh) * 100) + "%";
      layer.appendChild(dot);
    });

    return layer;
  }

  function zoneOverlayOpacity(zoneId) {
    var overlay = state.heatmapZones[zoneId];
    if (!state.heatmapEnabled || !overlay) {
      return 1;
    }
    if (overlay.density_level === "high") {
      return 0.9;
    }
    if (overlay.density_level === "medium") {
      return 0.96;
    }
    return 1;
  }

  function renderMap() {
    clearNode(warehouseMap);

    state.zones.forEach(function (zone) {
      var zoneCard = document.createElement("section");
      var zoneHeader = document.createElement("div");
      var zoneTitle = document.createElement("h3");
      var zoneSubtitle = document.createElement("p");
      var zoneProgress = document.createElement("div");
      var zoneProgressFill = document.createElement("div");
      var zoneCount = document.createElement("p");
      var zoneSlotGrid = document.createElement("div");
      var zoneEmptyState = document.createElement("div");
      var occupied = 0;
      var fillRatio;
      var groupedByAisle = {};
      var aisleOrder = [];
      var maxSlotsPerAisle = 0;
      var showEmptyZoneState;

      zoneCard.className = "zone-card zone-" + zoneKey(zone);
      zoneCard.style.opacity = String(zoneOverlayOpacity(zone.zone_id));

      zoneHeader.className = "zone-header";
      zoneTitle.className = "zone-title";
      zoneSubtitle.className = "zone-subtitle";
      zoneProgress.className = "zone-progress";
      zoneProgressFill.className = "zone-progress-fill";
      zoneCount.className = "zone-count";
      zoneSlotGrid.className = "zone-slot-grid";
      zoneEmptyState.className = "zone-empty-state";
      zoneEmptyState.textContent = "No active slots";

      zoneTitle.textContent = zone.zone_name || "";
      zoneSubtitle.textContent = String(zone.zone_type || "").toUpperCase();

      (zone.slots || []).forEach(function (slot) {
        if (slot.is_occupied || slot.quantity > 0 || slot.sku_id) {
          occupied += 1;
        }
        if (!groupedByAisle[slotAisleLabel(slot)]) {
          groupedByAisle[slotAisleLabel(slot)] = [];
          aisleOrder.push(slotAisleLabel(slot));
        }
        groupedByAisle[slotAisleLabel(slot)].push(slot);
      });
      fillRatio = zone.slots && zone.slots.length ? (occupied / zone.slots.length) * 100 : 0;
      maxSlotsPerAisle = aisleOrder.reduce(function (maxValue, aisleLabel) {
        return Math.max(maxValue, groupedByAisle[aisleLabel].length);
      }, 0);
      showEmptyZoneState =
        occupied === 0 &&
        (zoneKey(zone) === "receiving" || zoneKey(zone) === "dispatch");

      zoneProgressFill.style.width = fillRatio + "%";
      zoneCount.textContent = occupied + " / " + (zone.slots ? zone.slots.length : 0) + " slots filled";

      if (!showEmptyZoneState) {
        aisleOrder.forEach(function (aisleLabel) {
          var row = document.createElement("div");
          var rowLabel = document.createElement("div");
          var rowCells = document.createElement("div");

          row.className = "zone-aisle-row";
          rowLabel.className = "zone-aisle-label";
          rowCells.className = "zone-aisle-cells";
          rowCells.style.setProperty("--row-columns", String(maxSlotsPerAisle));
          rowLabel.textContent = aisleLabel;

          if (aisleLabel === aisleOrder[aisleOrder.length - 1]) {
            row.style.borderBottom = "0";
          }

          groupedByAisle[aisleLabel].forEach(function (slot) {
            var slotNode = document.createElement("button");
            var isOccupied = slot.is_occupied || slot.quantity > 0 || slot.sku_id;

            slotNode.type = "button";
            slotNode.className = "warehouse-slot " + (isOccupied ? zoneOccupiedClass(zone) : "is-empty");
            slotNode.setAttribute("aria-label", slot.slot_id || "slot");
            slotNode.textContent = slotShortLabel(slot);
            applySlotColor(slotNode, zone, slot);

            if (state.selectedSlot && state.selectedSlot.slot_id === slot.slot_id) {
              slotNode.classList.add("is-selected");
            }

            slotNode.addEventListener("mouseenter", function (event) {
              state.hoveredSlot = slot.slot_id;
              updateTooltip(slot.slot_id, event);
            });
            slotNode.addEventListener("mousemove", function (event) {
              updateTooltip(slot.slot_id, event);
            });
            slotNode.addEventListener("mouseleave", function () {
              state.hoveredSlot = null;
              hideTooltip();
            });
            slotNode.addEventListener("click", function () {
              var currentSlot = findSlotById(slot.slot_id);
              var occupiedNow = currentSlot && (currentSlot.is_occupied || currentSlot.quantity > 0 || currentSlot.sku_id);
              if (occupiedNow) {
                state.selectedSlot = currentSlot;
                updatePanel(currentSlot);
              } else {
                state.selectedSlot = null;
                updatePanel(null);
              }
              renderMap();
            });

            rowCells.appendChild(slotNode);
          });

          while (rowCells.children.length < maxSlotsPerAisle) {
            var ghost = document.createElement("span");
            ghost.className = "warehouse-slot is-empty is-ghost";
            ghost.setAttribute("aria-hidden", "true");
            rowCells.appendChild(ghost);
          }

          row.appendChild(rowLabel);
          row.appendChild(rowCells);
          zoneSlotGrid.appendChild(row);
        });
      }

      zoneProgress.appendChild(zoneProgressFill);
      zoneHeader.appendChild(zoneTitle);
      zoneHeader.appendChild(zoneSubtitle);
      zoneHeader.appendChild(zoneProgress);
      zoneHeader.appendChild(zoneCount);

      zoneCard.appendChild(zoneHeader);
      zoneCard.appendChild(showEmptyZoneState ? zoneEmptyState : zoneSlotGrid);
      zoneCard.appendChild(buildWorkerLayer(zone));
      warehouseMap.appendChild(zoneCard);
    });
  }

  function clearTimers() {
    if (state.floorTimerId) {
      window.clearInterval(state.floorTimerId);
      state.floorTimerId = null;
    }
    if (state.assetsTimerId) {
      window.clearInterval(state.assetsTimerId);
      state.assetsTimerId = null;
    }
  }

  function stopLoginMetricsPolling() {
    if (state.loginMetricsTimerId) {
      window.clearInterval(state.loginMetricsTimerId);
      state.loginMetricsTimerId = null;
    }
  }

  function loadLoginMetrics() {
    return fetch("/api/login-metrics", {
      credentials: "include"
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Login metrics request failed");
        }
        return response.json();
      })
      .then(function (payload) {
        loginMetricsFallback = payload;
        updateLoginMetrics(payload);
        return payload;
      })
      .catch(function () {
        updateLoginMetrics(null);
      });
  }

  function startLoginMetricsPolling() {
    stopLoginMetricsPolling();
    updateLoginMetrics(loginMetricsFallback);
    loadLoginMetrics();
    state.loginMetricsTimerId = window.setInterval(loadLoginMetrics, 15000);
  }

  function startPolling() {
    clearTimers();
    state.floorTimerId = window.setInterval(loadFloor, 10000);
    state.assetsTimerId = window.setInterval(loadAssets, 5000);
  }

  function loadFloor() {
    if (!state.authenticated) {
      return Promise.resolve();
    }

    setStatus("Loading floor data...");
    return apiFetch("/api/floor")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Floor request failed with status " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        state.slots = [];
        state.zones = (data.zones || []).map(function (zone) {
          var nextZone = {};
          Object.keys(zone).forEach(function (key) {
            nextZone[key] = zone[key];
          });
          nextZone.slots = (zone.slots || []).map(function (slot) {
            var normalized = applyOverride(cloneSlot(slot, zone));
            state.slots.push(normalized);
            return normalized;
          }).sort(function (left, right) {
            var leftKey = slotSortValue(left);
            var rightKey = slotSortValue(right);
            if (leftKey < rightKey) {
              return -1;
            }
            if (leftKey > rightKey) {
              return 1;
            }
            return 0;
          });
          return nextZone;
        });
        syncSelectedSlot();
        state.floorLoadedAt = new Date();
        updateMetrics();
        renderMap();
        emitFloorUpdated();
        setStatus("Floor loaded. Responsive grid synchronized.");
      })
      .catch(function (error) {
        setStatus(error.message);
      });
  }

  function loadAssets() {
    if (!state.authenticated || state.assetsRequestInFlight) {
      return;
    }
    state.assetsRequestInFlight = true;
    apiFetch("/api/assets")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Asset request failed with status " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        state.assets = (data.assets || []).map(function (asset) {
          return {
            asset_id: asset.asset_id,
            asset_type: asset.asset_type,
            x: normalizeNumber(asset.x),
            y: normalizeNumber(asset.y),
            status: asset.status,
            updated_at: asset.updated_at
          };
        });
        state.assetsLoadedAt = new Date();
        updateMetrics();
        renderMap();
        setStatus("Worker beacons refreshed.");
      })
      .catch(function (error) {
        setStatus(error.message);
      })
      .finally(function () {
        state.assetsRequestInFlight = false;
      });
  }

  function loadHeatmap() {
    if (!state.authenticated || state.heatmapRequestInFlight) {
      return Promise.resolve();
    }
    state.heatmapRequestInFlight = true;
    return apiFetch("/api/heatmap")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Heatmap request failed with status " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        var overlays = {};
        (data.zones || []).forEach(function (zone) {
          overlays[zone.zone_id] = zone;
        });
        state.heatmapZones = overlays;
        renderMap();
      })
      .catch(function (error) {
        setStatus(error.message);
      })
      .finally(function () {
        state.heatmapRequestInFlight = false;
      });
  }

  function startDashboard() {
    showAuthenticatedView();
    startPolling();
    return loadFloor().then(function () {
      loadAssets();
      if (state.heatmapEnabled) {
        return loadHeatmap();
      }
      return Promise.resolve();
    });
  }

  function handleLoginSubmit(event) {
    event.preventDefault();
    setLoginError("");
    loginButton.disabled = true;
    loginButton.innerHTML = loginButtonMarkup("Signing in");

    apiFetch("/api/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        username: loginUsername.value,
        password: loginPassword.value
      })
    })
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (payload) {
            throw new Error(payload.detail || "Login failed");
          });
        }
        return response.json();
      })
      .then(function (payload) {
        state.authenticated = true;
        state.username = payload.username;
        loginPassword.value = "";
        dispatchAuthChanged();
        return startDashboard();
      })
      .catch(function (error) {
        setLoginError(error.message);
      })
      .finally(function () {
        loginButton.disabled = false;
        loginButton.innerHTML = loginButtonMarkup("Sign in");
      });
  }

  function handleLogout() {
    apiFetch("/api/logout", {
      method: "POST"
    })
      .finally(function () {
        clearTimers();
        handleUnauthorized();
      });
  }

  function bootstrapAuth() {
    return fetch("/api/session", {
      credentials: "include"
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Session check failed");
        }
        return response.json();
      })
      .then(function (payload) {
        state.authenticated = !!payload.authenticated;
        state.username = payload.username || null;
        dispatchAuthChanged();
        if (state.authenticated) {
          return startDashboard();
        }
        showLoggedOutView();
        loginUsername.focus();
        return Promise.resolve();
      })
      .catch(function () {
        showLoggedOutView();
      });
  }

  loginForm.addEventListener("submit", handleLoginSubmit);
  logoutButton.addEventListener("click", handleLogout);
  navAnalytics.addEventListener("click", function () {
    if (!state.authenticated) {
      return;
    }
    setActiveView("analytics");
  });
  navUpload.addEventListener("click", function () {
    if (!state.authenticated) {
      return;
    }
    setActiveView("upload");
  });
  navMap.addEventListener("click", function () {
    if (!state.authenticated) {
      return;
    }
    setActiveView("map");
  });
  navForecast.addEventListener("click", function () {
    if (!state.authenticated) {
      return;
    }
    setActiveView("forecast");
  });

  heatmapToggle.addEventListener("click", function () {
    if (!state.authenticated) {
      return;
    }
    state.heatmapEnabled = !state.heatmapEnabled;
    heatmapToggle.classList.toggle("active", state.heatmapEnabled);
    heatmapToggle.textContent = state.heatmapEnabled ? "Heatmap On" : "Heatmap Off";
    heatmapToggle.setAttribute("aria-pressed", state.heatmapEnabled ? "true" : "false");
    heatmapLegend.classList.toggle("hidden", !state.heatmapEnabled);
    if (state.heatmapEnabled) {
      loadHeatmap();
    } else {
      renderMap();
    }
  });

  window.addEventListener("recommendation-accepted", function (event) {
    var detail = event.detail || {};
    handleRecommendationAccepted(detail);
  });

  window.addEventListener("inventory-assigned", function () {
    loadFloor().then(function () {
      if (state.heatmapEnabled) {
        loadHeatmap();
      }
    });
  });

  window.addEventListener("warehouse-queue-updated", function (event) {
    var detail = event.detail || {};
    state.queueCount = normalizeNumber(detail.count);
    state.queueSavings = normalizeNumber(detail.total_meters_saved);
    updateMetrics();
  });

  updatePanel(null);
  setActiveView("analytics");
  showLoggedOutView();
  renderMap();
  bootstrapAuth();
}());
