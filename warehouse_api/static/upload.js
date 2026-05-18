(function () {
  var form = document.getElementById("inventory-upload-form");
  var skuIdInput = document.getElementById("upload-sku-id");
  var skuStatus = document.getElementById("upload-sku-status");
  var skuNameInput = document.getElementById("upload-sku-name");
  var categoryInput = document.getElementById("upload-category");
  var quantityInput = document.getElementById("upload-quantity");
  var unitWeightInput = document.getElementById("upload-unit-weight");
  var supplierInput = document.getElementById("upload-supplier");
  var notesInput = document.getElementById("upload-notes");
  var formMessage = document.getElementById("upload-form-message");
  var recommendButton = document.getElementById("upload-recommend-button");
  var recommendButtonText = document.getElementById("upload-recommend-button-text");
  var recommendationEmpty = document.getElementById("upload-recommendation-empty");
  var recommendationResult = document.getElementById("upload-recommendation-result");
  var recommendedSlotId = document.getElementById("recommended-slot-id");
  var recommendedZoneName = document.getElementById("recommended-zone-name");
  var reasonDistance = document.getElementById("reason-distance");
  var reasonZoneType = document.getElementById("reason-zone-type");
  var reasonOccupancy = document.getElementById("reason-occupancy");
  var reasonSaving = document.getElementById("reason-saving");
  var miniMapPreview = document.getElementById("mini-map-preview");
  var miniMapCaption = document.getElementById("mini-map-caption");
  var confirmButton = document.getElementById("confirm-assignment-button");
  var differentSlotButton = document.getElementById("different-slot-button");
  var recentUploadsBody = document.getElementById("recent-uploads-body");
  var inboundRefresh = document.getElementById("inbound-log-refresh");
  var toastRoot = document.getElementById("toast-root");

  if (!form) {
    return;
  }

  var state = {
    authenticated: false,
    skuKnown: null,
    recommendBusy: false,
    assignBusy: false,
    recommendation: null,
    excludedSlots: [],
    todayTimerId: null
  };

  function getApiFetch() {
    return window.warehouseFetch || fetch;
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
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

  function normalizeNumber(value) {
    if (value === null || value === undefined || value === "") {
      return 0;
    }
    return Number(value);
  }

  function setFormMessage(message) {
    if (!message) {
      formMessage.textContent = "";
      formMessage.classList.add("hidden");
      return;
    }
    formMessage.textContent = message;
    formMessage.classList.remove("hidden");
  }

  function setSkuStatus(kind, message) {
    if (!kind || !message) {
      skuStatus.textContent = "";
      skuStatus.className = "status-inline hidden";
      return;
    }

    skuStatus.textContent = message;
    skuStatus.className = "status-inline status-inline-" + kind;
  }

  function setKnownSkuMode(isKnown) {
    skuNameInput.readOnly = !!isKnown;
    categoryInput.readOnly = !!isKnown;
    skuNameInput.classList.toggle("is-readonly", !!isKnown);
    categoryInput.classList.toggle("is-readonly", !!isKnown);
  }

  function getFormPayload() {
    return {
      sku_id: String(skuIdInput.value || "").trim(),
      sku_name: String(skuNameInput.value || "").trim(),
      category: String(categoryInput.value || "").trim(),
      quantity: Number(quantityInput.value || 0),
      unit_weight: unitWeightInput.value === "" ? null : Number(unitWeightInput.value),
      supplier: String(supplierInput.value || "").trim(),
      notes: String(notesInput.value || "").trim()
    };
  }

  function validatePayload(payload) {
    if (!payload.sku_id) {
      throw new Error("SKU ID is required.");
    }
    if (!payload.quantity || payload.quantity < 1) {
      throw new Error("Quantity must be at least 1.");
    }
  }

  function resetRecommendation() {
    state.recommendation = null;
    state.excludedSlots = [];
    recommendationResult.classList.add("hidden");
    recommendationEmpty.classList.remove("hidden");
    recommendedSlotId.textContent = "-";
    recommendedZoneName.textContent = "-";
    reasonDistance.textContent = "-";
    reasonZoneType.textContent = "-";
    reasonOccupancy.textContent = "-";
    reasonSaving.textContent = "-";
    miniMapCaption.textContent = "Awaiting floor data";
    miniMapPreview.className = "mini-map-preview";
    miniMapPreview.textContent = "";
    clearNode(miniMapPreview);
  }

  function resetForm() {
    form.reset();
    setFormMessage("");
    setSkuStatus(null, null);
    setKnownSkuMode(false);
    state.skuKnown = null;
    resetRecommendation();
  }

  function setRecommendBusy(isBusy) {
    state.recommendBusy = isBusy;
    recommendButton.disabled = isBusy;
    recommendButton.classList.toggle("is-loading", isBusy);
    recommendButtonText.textContent = isBusy ? "Loading Recommendation..." : "Get Slot Recommendation";
  }

  function setAssignBusy(isBusy) {
    state.assignBusy = isBusy;
    confirmButton.disabled = isBusy;
    differentSlotButton.disabled = isBusy;
    confirmButton.textContent = isBusy ? "Assigning..." : "✓ Confirm & Assign";
    differentSlotButton.textContent = isBusy ? "Refreshing..." : "↺ Get Different Slot";
  }

  function showToast(message, tone) {
    var toast = document.createElement("div");
    var timerId;

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
    }, 4000);

    toast.addEventListener("click", function () {
      window.clearTimeout(timerId);
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    });
  }

  function renderMiniMap(slotId) {
    var shell = window.WarehouseShell;
    var snapshot = shell && shell.getFloorSnapshot ? shell.getFloorSnapshot() : null;
    var slots;
    var bounds;

    clearNode(miniMapPreview);

    if (!snapshot || !snapshot.slots || !snapshot.slots.length) {
      miniMapCaption.textContent = "Floor telemetry pending";
      miniMapPreview.className = "mini-map-preview is-empty";
      miniMapPreview.textContent = "Mini map will appear after the live floor sync.";
      return;
    }

    slots = snapshot.slots;
    bounds = slots.reduce(function (memo, slot) {
      var x = normalizeNumber(slot.x);
      var y = normalizeNumber(slot.y);
      var w = normalizeNumber(slot.width);
      var h = normalizeNumber(slot.height);
      memo.minX = Math.min(memo.minX, x);
      memo.minY = Math.min(memo.minY, y);
      memo.maxX = Math.max(memo.maxX, x + w);
      memo.maxY = Math.max(memo.maxY, y + h);
      return memo;
    }, {
      minX: Number.POSITIVE_INFINITY,
      minY: Number.POSITIVE_INFINITY,
      maxX: 0,
      maxY: 0
    });

    miniMapPreview.className = "mini-map-preview";
    miniMapCaption.textContent = slots.length + " slots tracked";

    slots.forEach(function (slot) {
      var dot = document.createElement("span");
      var width = Math.max(1, bounds.maxX - bounds.minX);
      var height = Math.max(1, bounds.maxY - bounds.minY);
      var left = ((normalizeNumber(slot.x) - bounds.minX) / width) * 100;
      var top = ((normalizeNumber(slot.y) - bounds.minY) / height) * 100;
      var isTarget = slot.slot_id === slotId;

      dot.className = "mini-map-dot" + (isTarget ? " is-target" : "");
      dot.style.left = left + "%";
      dot.style.top = top + "%";
      miniMapPreview.appendChild(dot);

      if (isTarget) {
        var label = document.createElement("div");
        label.className = "mini-map-label";
        label.textContent = slot.slot_id;
        label.style.left = left + "%";
        label.style.top = top + "%";
        miniMapPreview.appendChild(label);
      }
    });
  }

  function renderRecommendation() {
    if (!state.recommendation) {
      resetRecommendation();
      return;
    }

    recommendationEmpty.classList.add("hidden");
    recommendationResult.classList.remove("hidden");
    recommendedSlotId.textContent = state.recommendation.slot_id || "-";
    recommendedZoneName.textContent = state.recommendation.zone || "-";
    reasonDistance.textContent = Number(state.recommendation.distance_to_dispatch || 0).toFixed(1) + " m";
    reasonZoneType.textContent = state.recommendation.zone_type || "-";
    reasonOccupancy.textContent = Number(state.recommendation.occupancy_pct || 0).toFixed(1) + "%";
    reasonSaving.textContent = Number(state.recommendation.estimated_saving || 0).toFixed(1) + " m";
    renderMiniMap(state.recommendation.slot_id);
  }

  function applySkuLookup(payload) {
    state.skuKnown = !!payload.exists;

    if (payload.exists) {
      skuNameInput.value = payload.sku_name || "";
      categoryInput.value = payload.category || "";
      if (payload.unit_weight !== null && payload.unit_weight !== undefined && unitWeightInput.value === "") {
        unitWeightInput.value = String(payload.unit_weight);
      }
      setSkuStatus("known", "✓ Known SKU");
      setKnownSkuMode(true);
    } else {
      if (!skuNameInput.value) {
        skuNameInput.value = "";
      }
      if (!categoryInput.value) {
        categoryInput.value = "";
      }
      setSkuStatus("new", "⚠ New SKU — will be created");
      setKnownSkuMode(false);
    }
  }

  function fetchSkuDetails() {
    var skuId = String(skuIdInput.value || "").trim();

    if (!state.authenticated || !skuId) {
      state.skuKnown = null;
      setSkuStatus(null, null);
      setKnownSkuMode(false);
      return Promise.resolve();
    }

    return getApiFetch()("/api/skus/" + encodeURIComponent(skuId))
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (payload) {
            throw new Error(payload.detail || "SKU lookup failed");
          });
        }
        return response.json();
      })
      .then(function (payload) {
        applySkuLookup(payload);
      })
      .catch(function (error) {
        setSkuStatus("warning", error.message);
      });
  }

  function requestRecommendation() {
    var payload = getFormPayload();

    try {
      validatePayload(payload);
    } catch (validationError) {
      setFormMessage(validationError.message);
      return Promise.resolve();
    }

    setFormMessage("");
    setRecommendBusy(true);
    return getApiFetch()("/api/inventory/recommend", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        sku_id: payload.sku_id,
        quantity: payload.quantity,
        category: payload.category,
        exclude_slots: state.excludedSlots
      })
    })
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (body) {
            throw new Error(body.detail || "Recommendation lookup failed");
          });
        }
        return response.json();
      })
      .then(function (body) {
        state.recommendation = body;
        renderRecommendation();
      })
      .catch(function (error) {
        setFormMessage(error.message);
      })
      .finally(function () {
        setRecommendBusy(false);
      });
  }

  function assignRecommendation() {
    var payload = getFormPayload();

    if (!state.recommendation) {
      setFormMessage("Generate a recommendation before assigning inventory.");
      return;
    }

    try {
      validatePayload(payload);
    } catch (validationError) {
      setFormMessage(validationError.message);
      return;
    }

    setFormMessage("");
    setAssignBusy(true);
    getApiFetch()("/api/inventory/assign", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        sku_id: payload.sku_id,
        slot_id: state.recommendation.slot_id,
        quantity: payload.quantity,
        sku_name: payload.sku_name,
        category: payload.category,
        unit_weight: payload.unit_weight,
        supplier: payload.supplier,
        notes: payload.notes
      })
    })
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (body) {
            throw new Error(body.detail || "Assignment failed");
          });
        }
        return response.json();
      })
      .then(function (body) {
        showToast(
          "✓ " + payload.sku_id + " assigned to " + body.slot_id + " in " + body.zone,
          "success"
        );
        resetForm();
        loadTodayLog();
        window.dispatchEvent(
          new CustomEvent("inventory-assigned", {
            detail: {
              sku_id: body.sku_id,
              slot_id: body.slot_id
            }
          })
        );
      })
      .catch(function (error) {
        setFormMessage(error.message);
      })
      .finally(function () {
        setAssignBusy(false);
      });
  }

  function requestDifferentSlot() {
    if (!state.recommendation || !state.recommendation.slot_id) {
      return;
    }

    if (state.excludedSlots.indexOf(state.recommendation.slot_id) === -1) {
      state.excludedSlots.push(state.recommendation.slot_id);
    }
    setAssignBusy(true);
    requestRecommendation().finally(function () {
      setAssignBusy(false);
    });
  }

  function renderInboundLog(items) {
    clearNode(recentUploadsBody);

    if (!items.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.colSpan = 7;
      emptyCell.className = "table-empty";
      emptyCell.textContent = "No inbound uploads recorded yet.";
      emptyRow.appendChild(emptyCell);
      recentUploadsBody.appendChild(emptyRow);
      return;
    }

    items.forEach(function (item) {
      var row = document.createElement("tr");
      var cells = [
        formatTime(item.moved_at),
        item.sku_id || "-",
        item.sku_name || "-",
        String(item.quantity || 0),
        item.assigned_slot || "-",
        item.zone || "-"
      ];

      cells.forEach(function (value) {
        var cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });

      var statusCell = document.createElement("td");
      var badge = document.createElement("span");
      var statusValue = String(item.status || "Pending");
      badge.className = "status-badge " + (statusValue.toLowerCase() === "assigned" ? "is-assigned" : "is-pending");
      badge.textContent = statusValue;
      statusCell.appendChild(badge);
      row.appendChild(statusCell);
      recentUploadsBody.appendChild(row);
    });
  }

  function loadTodayLog() {
    if (!state.authenticated) {
      renderInboundLog([]);
      inboundRefresh.textContent = "Sign in to load inbound activity";
      return;
    }

    getApiFetch()("/api/inventory/today")
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (body) {
            throw new Error(body.detail || "Inbound log request failed");
          });
        }
        return response.json();
      })
      .then(function (body) {
        renderInboundLog(body.items || []);
        inboundRefresh.textContent = "Updated " + formatTime(new Date());
      })
      .catch(function (error) {
        inboundRefresh.textContent = error.message;
      });
  }

  function startTodayPolling() {
    if (state.todayTimerId) {
      window.clearInterval(state.todayTimerId);
    }
    state.todayTimerId = window.setInterval(loadTodayLog, 30000);
  }

  function stopTodayPolling() {
    if (state.todayTimerId) {
      window.clearInterval(state.todayTimerId);
      state.todayTimerId = null;
    }
  }

  skuIdInput.addEventListener("blur", fetchSkuDetails);
  skuIdInput.addEventListener("input", function () {
    state.skuKnown = null;
    setSkuStatus(null, null);
    setKnownSkuMode(false);
    resetRecommendation();
    setFormMessage("");
  });

  skuNameInput.addEventListener("input", function () {
    resetRecommendation();
  });
  categoryInput.addEventListener("input", function () {
    resetRecommendation();
  });
  quantityInput.addEventListener("input", function () {
    resetRecommendation();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    requestRecommendation();
  });

  confirmButton.addEventListener("click", assignRecommendation);
  differentSlotButton.addEventListener("click", requestDifferentSlot);

  window.addEventListener("warehouse-floor-updated", function () {
    if (state.recommendation) {
      renderMiniMap(state.recommendation.slot_id);
    }
  });

  window.addEventListener("warehouse-auth-changed", function (event) {
    var detail = event.detail || {};
    state.authenticated = !!detail.authenticated;

    if (state.authenticated) {
      loadTodayLog();
      startTodayPolling();
      return;
    }

    stopTodayPolling();
    resetForm();
    renderInboundLog([]);
    inboundRefresh.textContent = "Sign in to load inbound activity";
  });

  if (window.WarehouseShell && window.WarehouseShell.isAuthenticated()) {
    state.authenticated = true;
    loadTodayLog();
    startTodayPolling();
  } else {
    renderInboundLog([]);
    resetRecommendation();
  }
}());
