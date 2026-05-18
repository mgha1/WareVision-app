(function () {
  var ReactApi = window.React;
  var ReactDomApi = window.ReactDOM;
  var mountNode = document.getElementById("recommendations-root");

  if (!ReactApi || !ReactDomApi || !mountNode) {
    return;
  }

  var useEffect = ReactApi.useEffect;
  var useMemo = ReactApi.useMemo;
  var useState = ReactApi.useState;
  var element = ReactApi.createElement;

  function getApiFetch() {
    return window.warehouseFetch || fetch;
  }

  function formatMeters(value) {
    return Number(value || 0).toFixed(1);
  }

  function formatTimestamp(value) {
    if (!value) {
      return "Waiting for first refresh";
    }
    return new Date(value).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function RecommendationSidebar() {
    var _useState = useState([]);
    var recommendations = _useState[0];
    var setRecommendations = _useState[1];

    var _useState2 = useState(false);
    var loading = _useState2[0];
    var setLoading = _useState2[1];

    var _useState3 = useState(null);
    var error = _useState3[0];
    var setError = _useState3[1];

    var _useState4 = useState({});
    var accepting = _useState4[0];
    var setAccepting = _useState4[1];

    var _useState5 = useState(false);
    var authenticated = _useState5[0];
    var setAuthenticated = _useState5[1];

    var _useState6 = useState(null);
    var lastLoadedAt = _useState6[0];
    var setLastLoadedAt = _useState6[1];

    var summary = useMemo(function () {
      var total = 0;
      for (var index = 0; index < recommendations.length; index += 1) {
        total += Number(recommendations[index].saving_m || 0);
      }
      return {
        total_meters_saved: total,
        count: recommendations.length
      };
    }, [recommendations]);

    function emitSummary(nextSummary) {
      window.dispatchEvent(
        new CustomEvent("warehouse-queue-updated", {
          detail: nextSummary
        })
      );
    }

    function loadRecommendations() {
      if (!authenticated) {
        setRecommendations([]);
        setLoading(false);
        setError(null);
        emitSummary({
          count: 0,
          total_meters_saved: 0
        });
        return;
      }

      setLoading(true);
      setError(null);
      getApiFetch()("/api/recommendations")
        .then(function (response) {
          if (!response.ok) {
            throw new Error("Recommendations request failed with status " + response.status);
          }
          return response.json();
        })
        .then(function (payload) {
          var nextRecommendations = payload.recommendations || [];
          var nextSummary = payload.summary || {
            count: nextRecommendations.length,
            total_meters_saved: 0
          };
          setRecommendations(nextRecommendations);
          setLastLoadedAt(new Date());
          emitSummary(nextSummary);
        })
        .catch(function (fetchError) {
          setError(fetchError.message);
        })
        .finally(function () {
          setLoading(false);
        });
    }

    function acceptRecommendation(recommendation) {
      setAccepting(function (current) {
        var next = {};
        Object.keys(current).forEach(function (key) {
          next[key] = current[key];
        });
        next[recommendation.rec_id] = true;
        return next;
      });
      setError(null);

      getApiFetch()("/api/accept-recommendation", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ rec_id: recommendation.rec_id })
      })
        .then(function (response) {
          if (!response.ok) {
            return response.json().then(function (payload) {
              throw new Error(payload.detail || "Accept failed");
            });
          }
          return response.json();
        })
        .then(function (payload) {
          window.dispatchEvent(
            new CustomEvent("recommendation-accepted", {
              detail: {
                rec_id: payload.rec_id,
                from_slot: payload.from_slot,
                to_slot: payload.to_slot
              }
            })
          );
          loadRecommendations();
        })
        .catch(function (acceptError) {
          setError(acceptError.message);
        })
        .finally(function () {
          setAccepting(function (current) {
            var next = {};
            Object.keys(current).forEach(function (key) {
              if (String(key) !== String(recommendation.rec_id)) {
                next[key] = current[key];
              }
            });
            return next;
          });
        });
    }

    useEffect(function () {
      function handleAuthChange(event) {
        var detail = event.detail || {};
        var nextAuthenticated = !!detail.authenticated;
        setAuthenticated(nextAuthenticated);
      }

      window.addEventListener("warehouse-auth-changed", handleAuthChange);
      if (window.WarehouseShell && window.WarehouseShell.isAuthenticated()) {
        setAuthenticated(true);
      }

      return function () {
        window.removeEventListener("warehouse-auth-changed", handleAuthChange);
      };
    }, []);

    useEffect(function () {
      loadRecommendations();
      if (!authenticated) {
        return undefined;
      }

      var timerId = window.setInterval(loadRecommendations, 8000);
      return function () {
        window.clearInterval(timerId);
      };
    }, [authenticated]);

    var header = element(
      "div",
      { className: "rec-header" },
      element(
        "div",
        null,
        element("p", { className: "eyebrow" }, "Recommendations"),
        element("h3", null, "Slotting Queue"),
        element(
          "p",
          { className: "rec-caption" },
          "Keep high-value moves visible while you inspect the live warehouse floor."
        )
      ),
      element(
        "div",
        { className: "rec-meta-chip" },
        element("strong", null, recommendations.length),
        element("span", null, "Pending")
      )
    );

    var summaryCard = element(
      "div",
      { className: "rec-summary" },
      element("p", { className: "rec-summary-label" }, "Daily Opportunity"),
      element("p", { className: "rec-summary-value" }, formatMeters(summary.total_meters_saved), "m"),
      element(
        "p",
        { className: "rec-summary-subtext" },
        summary.count,
        " recommendations currently waiting for operator action."
      )
    );

    var content;
    if (!authenticated) {
      content = element(
        "div",
        { className: "rec-empty" },
        "Log in to load the live slotting queue."
      );
    } else if (error) {
      content = element("div", { className: "rec-error" }, error);
    } else if (loading && recommendations.length === 0) {
      content = element("div", { className: "rec-empty" }, "Loading slotting suggestions...");
    } else if (recommendations.length === 0) {
      content = element("div", { className: "rec-empty" }, "No pending slotting suggestions.");
    } else {
      content = element(
        "div",
        { className: "rec-list" },
        recommendations.map(function (recommendation) {
          var busy = !!accepting[recommendation.rec_id];
          return element(
            "article",
            {
              key: recommendation.rec_id,
              className: "rec-card"
            },
            element(
              "div",
              { className: "rec-card-header" },
              element(
                "div",
                null,
                element("h4", null, recommendation.sku_name || recommendation.sku_id),
                element(
                  "p",
                  { className: "rec-card-path" },
                  recommendation.from_slot,
                  " -> ",
                  recommendation.to_slot
                )
              ),
              element(
                "button",
                {
                  className: "accept-button",
                  type: "button",
                  disabled: busy,
                  onClick: function () {
                    acceptRecommendation(recommendation);
                  }
                },
                busy ? "Applying..." : "Accept"
              )
            ),
            element(
              "p",
              { className: "rec-card-metric" },
              formatMeters(recommendation.saving_m),
              element("span", null, "meters saved / day")
            ),
            element(
              "p",
              { className: "rec-card-reason" },
              recommendation.ai_reason || "Suggested move based on pick path waste."
            )
          );
        })
      );
    }

    return element(
      "section",
      { className: "rec-sidebar" },
      header,
      summaryCard,
      content,
      element(
        "p",
        { className: "rec-status-line" },
        authenticated ? "Queue sync is active." : "Queue sync is paused."
      ),
      element(
        "p",
        { className: "rec-refresh" },
        "Last refresh: ",
        formatTimestamp(lastLoadedAt)
      )
    );
  }

  ReactDomApi.createRoot(mountNode).render(element(RecommendationSidebar));
}());
