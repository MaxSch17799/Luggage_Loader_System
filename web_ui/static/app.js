(function () {
  const bootstrap = window.APP_BOOTSTRAP || {};
  const schemaUrl = "/api/schema";
  const stateUrl = "/api/state";
  const parameterUrl = "/api/parameter";
  const nudgeUrl = "/api/nudge";
  const reloadUrl = "/api/reload";
  const clearPointsUrl = "/api/clear-points";
  const lidarPowerUrl = "/api/lidar-power";
  const shutdownUrl = "/api/shutdown";

  const sectionsRoot = document.getElementById("parameterSections");
  const metricsRoot = document.getElementById("metricsGrid");
  const hardwareGridEl = document.getElementById("hardwareGrid");
  const statusMessageEl = document.getElementById("statusMessage");
  const workerErrorEl = document.getElementById("workerError");
  const pointCounterEl = document.getElementById("pointCounter");
  const searchInputEl = document.getElementById("searchInput");
  const modeBadgeEl = document.getElementById("modeBadge");
  const configPathEl = document.getElementById("configPath");
  const reloadButtonEl = document.getElementById("reloadButton");
  const clearPointsButtonEl = document.getElementById("clearPointsButton");
  const lidarPowerButtonEl = document.getElementById("lidarPowerButton");
  const closeDemoButtonEl = document.getElementById("closeDemoButton");
  const canvasEl = document.getElementById("sceneCanvas");
  const canvasCtx = canvasEl.getContext("2d");

  let schema = null;
  let lastState = null;
  let pollInFlight = false;
  const controlsByPath = new Map();
  let infoBubbleEl = null;
  let infoBubbleContentEl = null;
  let infoBubbleTitleEl = null;
  let activeInfoButtonEl = null;

  const metricConfig = [
    { key: "status", label: "Status" },
    { key: "centerOffsetMm", label: "Center Offset", unit: "mm" },
    { key: "leftClearanceMm", label: "Left Clearance", unit: "mm" },
    { key: "rightClearanceMm", label: "Right Clearance", unit: "mm" },
    { key: "configuredTargetYmm", label: "Configured Target Y", unit: "mm" },
    { key: "liveForwardReturnMm", label: "Live Forward Return", unit: "mm" },
  ];

  function ensureInfoBubble() {
    if (infoBubbleEl) {
      return;
    }

    infoBubbleEl = document.createElement("div");
    infoBubbleEl.className = "info-bubble hidden";
    infoBubbleEl.innerHTML = `
      <div class="info-bubble-header">
        <div class="info-bubble-title"></div>
        <button type="button" class="info-bubble-close" aria-label="Close help bubble">×</button>
      </div>
      <div class="info-bubble-content"></div>
    `;

    infoBubbleTitleEl = infoBubbleEl.querySelector(".info-bubble-title");
    infoBubbleContentEl = infoBubbleEl.querySelector(".info-bubble-content");
    const closeButton = infoBubbleEl.querySelector(".info-bubble-close");
    closeButton.addEventListener("click", hideInfoBubble);
    document.body.append(infoBubbleEl);

    document.addEventListener("click", (event) => {
      if (!infoBubbleEl || infoBubbleEl.classList.contains("hidden")) {
        return;
      }
      if (infoBubbleEl.contains(event.target)) {
        return;
      }
      if (activeInfoButtonEl && activeInfoButtonEl.contains(event.target)) {
        return;
      }
      hideInfoBubble();
    });

    window.addEventListener("resize", hideInfoBubble);
    window.addEventListener(
      "scroll",
      () => {
        if (activeInfoButtonEl) {
          hideInfoBubble();
        }
      },
      true
    );
  }

  function hideInfoBubble() {
    if (!infoBubbleEl) {
      return;
    }
    infoBubbleEl.classList.add("hidden");
    if (activeInfoButtonEl) {
      activeInfoButtonEl.classList.remove("active");
      activeInfoButtonEl = null;
    }
  }

  function showInfoBubble(spec, buttonEl) {
    ensureInfoBubble();

    if (activeInfoButtonEl === buttonEl && !infoBubbleEl.classList.contains("hidden")) {
      hideInfoBubble();
      return;
    }

    if (activeInfoButtonEl) {
      activeInfoButtonEl.classList.remove("active");
    }

    activeInfoButtonEl = buttonEl;
    activeInfoButtonEl.classList.add("active");
    infoBubbleTitleEl.textContent = spec.path;
    infoBubbleContentEl.textContent =
      spec.helpText || "No extra help available for this parameter yet.";

    infoBubbleEl.classList.remove("hidden");

    const rect = buttonEl.getBoundingClientRect();
    const bubbleWidth = 360;
    const bubblePadding = 12;
    const top = Math.min(window.innerHeight - 180, rect.top + window.scrollY + 28);
    let left = rect.left + window.scrollX + 24;

    if (left + bubbleWidth > window.scrollX + window.innerWidth - bubblePadding) {
      left = window.scrollX + window.innerWidth - bubbleWidth - bubblePadding;
    }
    if (left < window.scrollX + bubblePadding) {
      left = window.scrollX + bubblePadding;
    }

    infoBubbleEl.style.top = `${Math.max(window.scrollY + bubblePadding, top)}px`;
    infoBubbleEl.style.left = `${left}px`;
    infoBubbleEl.style.width = `${bubbleWidth}px`;
  }

  function setStatus(message) {
    statusMessageEl.textContent = message || "Ready.";
  }

  function setWorkerError(message) {
    if (!message) {
      workerErrorEl.classList.add("hidden");
      workerErrorEl.textContent = "";
      return;
    }
    workerErrorEl.classList.remove("hidden");
    workerErrorEl.textContent = `Worker error: ${message}`;
  }

  function metricClassForStatus(value) {
    const upper = String(value || "").toUpperCase();
    if (upper.includes("STOP") || upper.includes("ERROR")) {
      return "danger";
    }
    if (upper.includes("LEFT") || upper.includes("RIGHT")) {
      return "warning";
    }
    if (upper.includes("CENTER")) {
      return "good";
    }
    return "";
  }

  function metricClassForNumeric(label, value) {
    if (value == null) {
      return "";
    }
    const absValue = Math.abs(Number(value));
    if (label === "Center Offset") {
      if (absValue <= 30) return "good";
      if (absValue <= 100) return "warning";
      return "danger";
    }
    if (label.includes("Clearance") || label.includes("Forward")) {
      if (absValue >= 300) return "good";
      if (absValue >= 100) return "warning";
      return "danger";
    }
    return "";
  }

  function formatMetricValue(item, value) {
    if (value == null) {
      return "No hit";
    }
    if (item.key === "status") {
      return String(value);
    }
    return `${Number(value).toFixed(1)} ${item.unit}`;
  }

  function renderMetrics(metrics) {
    metricsRoot.innerHTML = "";
    metricConfig.forEach((item) => {
      const value = metrics[item.key];
      const card = document.createElement("article");
      card.className = "metric-card";

      const label = document.createElement("div");
      label.className = "metric-label";
      label.textContent = item.label;

      const metricValue = document.createElement("div");
      metricValue.className = "metric-value";
      metricValue.textContent = formatMetricValue(item, value);

      if (item.key === "status") {
        metricValue.classList.add(metricClassForStatus(value));
      } else {
        const klass = metricClassForNumeric(item.label, value);
        if (klass) {
          metricValue.classList.add(klass);
        }
      }

      card.append(label, metricValue);
      metricsRoot.append(card);
    });
  }

  function hardwareTone(status) {
    const text = String(status || "").toLowerCase();
    if (text.includes("fix") || text.includes("running") || text.includes("updated") || text.includes("connected")) {
      return "good";
    }
    if (text.includes("error") || text.includes("failed") || text.includes("missing") || text.includes("offline")) {
      return "danger";
    }
    return "warning";
  }

  function formatOptionalNumber(value, digits = 2) {
    if (value == null || Number.isNaN(Number(value))) {
      return "n/a";
    }
    return Number(value).toFixed(digits);
  }

  function renderHardware(state) {
    const cards = [
      {
        title: "LiDAR",
        status: state.lidar?.available
          ? (state.lidar.running ? "Running" : "Stopped")
          : "Simulation mode",
        detail: state.lidar?.available
          ? `Port state: ${state.lidar.running ? "streaming" : "idle"}`
          : "No physical LiDAR in simulate mode.",
        extra: state.workerError ? "Traceback available in the red error strip." : null,
        error: state.workerError || null,
      },
      {
        title: "GPS",
        status: state.gps?.status || "GPS status unavailable",
        detail: `Port ${state.gps?.port || "n/a"} @ ${state.gps?.baudrate || "n/a"} baud`,
        extra: state.gps?.hasFix
          ? `Lat ${formatOptionalNumber(state.gps.latitude, 6)}, Lon ${formatOptionalNumber(state.gps.longitude, 6)}`
          : `Sentences ${state.gps?.sentenceCount ?? 0}, sats ${state.gps?.satellites ?? "n/a"}`,
        error: state.gps?.error || null,
      },
      {
        title: "LCD",
        status: state.lcd?.status || "LCD status unavailable",
        detail:
          state.lcd?.busNumber != null
            ? `i2c-${state.lcd.busNumber} at ${state.lcd.addressHex || "n/a"}`
            : `Configured bus ${state.parameterValues?.["lcd.i2c_bus"] ?? "n/a"}`,
        extra:
          Array.isArray(state.lcd?.detectedBuses) && state.lcd.detectedBuses.length > 0
            ? `Visible I2C buses: ${state.lcd.detectedBuses.map((bus) => `i2c-${bus}`).join(", ")}`
            : "No usable I2C bus detected yet.",
        error: state.lcd?.error || null,
      },
    ];

    hardwareGridEl.innerHTML = "";
    cards.forEach((card) => {
      const article = document.createElement("article");
      article.className = "hardware-card";

      const top = document.createElement("div");
      top.className = "hardware-card-top";

      const title = document.createElement("div");
      title.className = "hardware-title";
      title.textContent = card.title;

      const badge = document.createElement("div");
      badge.className = `hardware-badge ${hardwareTone(card.status)}`;
      badge.textContent = card.status;

      top.append(title, badge);

      const detail = document.createElement("div");
      detail.className = "hardware-detail";
      detail.textContent = card.detail;

      const extra = document.createElement("div");
      extra.className = "hardware-extra";
      extra.textContent = card.extra || "";

      article.append(top, detail, extra);

      if (card.error) {
        const error = document.createElement("div");
        error.className = "hardware-error";
        error.textContent = String(card.error).split("\n")[0];
        article.append(error);
      }

      hardwareGridEl.append(article);
    });
  }

  function createControl(spec) {
    const wrapper = document.createElement("div");
    wrapper.className = "param-controls";

    let inputEl;
    if (spec.kind === "enum" || spec.kind === "boolean") {
      inputEl = document.createElement("select");
      const values = spec.allowedValues || ["true", "false"];
      values.forEach((value) => {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = String(value);
        inputEl.append(option);
      });
      inputEl.addEventListener("change", () => {
        submitParameter(spec, inputEl.value);
      });
    } else {
      inputEl = document.createElement("input");
      inputEl.type = spec.kind === "integer" || spec.kind === "number" ? "number" : "text";
      if (spec.kind === "integer") {
        inputEl.step = "1";
      } else if (spec.kind === "number") {
        inputEl.step = spec.fineStep != null ? String(spec.fineStep) : "any";
      }
      inputEl.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          submitParameter(spec, inputEl.value);
        }
      });
      inputEl.addEventListener("blur", () => {
        submitParameter(spec, inputEl.value);
      });
    }

    controlsByPath.set(spec.path, inputEl);
    wrapper.append(inputEl);

    if (spec.kind !== "enum" && spec.kind !== "boolean") {
      const nudgeRow = document.createElement("div");
      nudgeRow.className = "nudge-row";

      [
        { label: "-", direction: -1, coarse: false },
        { label: "+", direction: 1, coarse: false },
        { label: "--", direction: -1, coarse: true },
        { label: "++", direction: 1, coarse: true },
      ].forEach((buttonSpec) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = buttonSpec.label;
        button.addEventListener("click", () => {
          nudgeParameter(spec, buttonSpec.direction, buttonSpec.coarse);
        });
        nudgeRow.append(button);
      });

      wrapper.append(nudgeRow);
    }

    return wrapper;
  }

  function renderSchema() {
    sectionsRoot.innerHTML = "";
    controlsByPath.clear();

    schema.sections.forEach((section, sectionIndex) => {
      const details = document.createElement("details");
      details.className = "parameter-section";
      details.open = sectionIndex < 3;

      const summary = document.createElement("summary");
      summary.textContent = section.name;
      details.append(summary);

      const list = document.createElement("div");
      list.className = "parameter-list";

      section.items.forEach((spec) => {
        const row = document.createElement("div");
        row.className = "param-row";
        row.dataset.path = spec.path.toLowerCase();
        row.dataset.search = `${spec.section} ${spec.key} ${spec.description} ${spec.helpText || ""}`.toLowerCase();

        const meta = document.createElement("div");
        meta.className = "param-meta";

        const header = document.createElement("div");
        header.className = "param-header";

        const label = document.createElement("div");
        label.className = "param-label";
        label.textContent = spec.key;

        const infoButton = document.createElement("button");
        infoButton.type = "button";
        infoButton.className = "info-button";
        infoButton.textContent = "i";
        infoButton.setAttribute("aria-label", `More info about ${spec.path}`);
        infoButton.title = `More info about ${spec.path}`;

        const path = document.createElement("div");
        path.className = "param-path";
        path.textContent = spec.path;

        const description = document.createElement("div");
        description.className = "param-description";
        description.textContent = spec.description;

        infoButton.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          showInfoBubble(spec, infoButton);
        });

        header.append(label, infoButton);
        meta.append(header, path, description);
        row.append(meta, createControl(spec));
        list.append(row);
      });

      details.append(list);
      sectionsRoot.append(details);
    });
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  async function submitParameter(spec, value) {
    try {
      const result = await postJson(parameterUrl, {
        section: spec.section,
        key: spec.key,
        value: value,
      });
      setStatus(result.message);
      await pollState(true);
    } catch (error) {
      setStatus(`Could not save ${spec.path}: ${error.message}`);
    }
  }

  async function nudgeParameter(spec, direction, coarse) {
    try {
      const result = await postJson(nudgeUrl, {
        section: spec.section,
        key: spec.key,
        direction,
        coarse,
      });
      setStatus(result.message);
      await pollState(true);
    } catch (error) {
      setStatus(`Could not nudge ${spec.path}: ${error.message}`);
    }
  }

  async function reloadToml() {
    try {
      const result = await postJson(reloadUrl, {});
      setStatus(result.message);
      await pollState(true);
    } catch (error) {
      setStatus(`Reload failed: ${error.message}`);
    }
  }

  async function clearPoints() {
    try {
      const result = await postJson(clearPointsUrl, {});
      setStatus(result.message);
      await pollState(true);
    } catch (error) {
      setStatus(`Clear points failed: ${error.message}`);
    }
  }

  async function toggleLidarPower() {
    try {
      const result = await postJson(lidarPowerUrl, {});
      setStatus(result.message);
      await pollState(true);
    } catch (error) {
      setStatus(`LiDAR power control failed: ${error.message}`);
    }
  }

  async function closeDemo() {
    const confirmed = window.confirm(
      "Close the Steer Clear demo, stop the background hardware workers, and shut down the browser server?"
    );
    if (!confirmed) {
      return;
    }

    try {
      const result = await postJson(shutdownUrl, {});
      setStatus(result.message);
      document.body.innerHTML = `
        <div style="padding:40px;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
          <h1 style="margin-top:0;">Steer Clear demo stopped</h1>
          <p>The background demo server has been shut down, the LiDAR stop request was sent, the GPS reader was stopped, and the LCD was released.</p>
          <p>You can now close this tab or return to the launcher terminal.</p>
        </div>
      `;
      window.setTimeout(() => {
        try {
          window.open("", "_self");
          window.close();
        } catch (_error) {
          /* ignore */
        }
      }, 250);
    } catch (error) {
      setStatus(`Close demo failed: ${error.message}`);
    }
  }

  function syncControls(parameterValues) {
    controlsByPath.forEach((inputEl, path) => {
      if (document.activeElement === inputEl) {
        return;
      }
      const value = parameterValues[path];
      if (value == null) {
        return;
      }
      const textValue = String(value);
      if (inputEl.value !== textValue) {
        inputEl.value = textValue;
      }
    });
  }

  function syncToolbar(state) {
    const lidar = state.lidar || { available: false, running: false, label: "LiDAR" };
    lidarPowerButtonEl.disabled = !lidar.available || !!state.shutdownRequested;
    lidarPowerButtonEl.textContent = lidar.available ? lidar.label : "Simulation mode";
    closeDemoButtonEl.disabled = !!state.shutdownRequested;
  }

  function filterParameters(query) {
    const normalized = query.trim().toLowerCase();
    const rows = sectionsRoot.querySelectorAll(".param-row");
    const sections = sectionsRoot.querySelectorAll(".parameter-section");

    rows.forEach((row) => {
      const haystack = row.dataset.search || "";
      row.hidden = normalized.length > 0 && !haystack.includes(normalized);
    });

    sections.forEach((section) => {
      const visibleRows = section.querySelectorAll(".param-row:not([hidden])");
      section.hidden = visibleRows.length === 0;
      if (normalized.length > 0 && visibleRows.length > 0) {
        section.open = true;
      }
    });
  }

  function resizeCanvas() {
    const ratio = window.devicePixelRatio || 1;
    const rect = canvasEl.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width * ratio));
    const height = Math.max(1, Math.round(rect.height * ratio));
    if (canvasEl.width !== width || canvasEl.height !== height) {
      canvasEl.width = width;
      canvasEl.height = height;
    }
    canvasCtx.setTransform(1, 0, 0, 1, 0, 0);
    canvasCtx.scale(ratio, ratio);
  }

  function makeWorldTransform(plot) {
    const rect = canvasEl.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const padLeft = 54;
    const padRight = 18;
    const padTop = 18;
    const padBottom = 34;
    const innerWidth = Math.max(1, width - padLeft - padRight);
    const innerHeight = Math.max(1, height - padTop - padBottom);

    return {
      width,
      height,
      padLeft,
      padRight,
      padTop,
      padBottom,
      toCanvasX(x) {
        return padLeft + ((x - plot.xMin) / (plot.xMax - plot.xMin)) * innerWidth;
      },
      toCanvasY(y) {
        return padTop + (1 - (y - plot.yMin) / (plot.yMax - plot.yMin)) * innerHeight;
      },
    };
  }

  function drawGrid(ctx, plot, tx) {
    const xSpan = plot.xMax - plot.xMin;
    const ySpan = plot.yMax - plot.yMin;
    const xStep = xSpan > 8 ? 1 : 0.5;
    const yStep = ySpan > 8 ? 1 : 0.5;

    ctx.save();
    ctx.strokeStyle = "rgba(102, 96, 80, 0.12)";
    ctx.fillStyle = "rgba(101, 97, 80, 0.85)";
    ctx.lineWidth = 1;
    ctx.font = "12px sans-serif";

    for (let x = Math.ceil(plot.xMin / xStep) * xStep; x <= plot.xMax + 1e-9; x += xStep) {
      const px = tx.toCanvasX(x);
      ctx.beginPath();
      ctx.moveTo(px, tx.padTop);
      ctx.lineTo(px, tx.height - tx.padBottom);
      ctx.stroke();
      ctx.fillText(x.toFixed(1), px - 10, tx.height - 10);
    }

    for (let y = Math.ceil(plot.yMin / yStep) * yStep; y <= plot.yMax + 1e-9; y += yStep) {
      const py = tx.toCanvasY(y);
      ctx.beginPath();
      ctx.moveTo(tx.padLeft, py);
      ctx.lineTo(tx.width - tx.padRight, py);
      ctx.stroke();
      ctx.fillText(y.toFixed(1), 10, py + 4);
    }

    ctx.restore();
  }

  function drawScene(state) {
    if (!state || !state.plot) {
      return;
    }

    resizeCanvas();
    const rect = canvasEl.getBoundingClientRect();
    const ctx = canvasCtx;
    const plot = state.plot;
    const tx = makeWorldTransform(plot);

    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = "#fffdf8";
    ctx.fillRect(0, 0, rect.width, rect.height);

    drawGrid(ctx, plot, tx);

    ctx.save();
    ctx.strokeStyle = "rgba(11, 125, 105, 0.18)";
    ctx.setLineDash([6, 6]);
    ctx.beginPath();
    ctx.moveTo(tx.toCanvasX(plot.lip.center), tx.padTop);
    ctx.lineTo(tx.toCanvasX(plot.lip.center), rect.height - tx.padBottom);
    ctx.stroke();

    ctx.strokeStyle = "rgba(214, 114, 34, 0.2)";
    ctx.beginPath();
    ctx.moveTo(tx.toCanvasX(plot.target.center), tx.padTop);
    ctx.lineTo(tx.toCanvasX(plot.target.center), rect.height - tx.padBottom);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.setLineDash([8, 5]);
    ctx.strokeStyle = "rgba(40, 92, 188, 0.65)";
    ctx.lineWidth = 1.5;
    const corridorX = tx.toCanvasX(plot.corridor.left);
    const corridorY = tx.toCanvasY(plot.corridor.top);
    const corridorWidth = tx.toCanvasX(plot.corridor.right) - tx.toCanvasX(plot.corridor.left);
    const corridorHeight = tx.toCanvasY(plot.corridor.bottom) - tx.toCanvasY(plot.corridor.top);
    ctx.strokeRect(corridorX, corridorY, corridorWidth, corridorHeight);
    ctx.restore();

    ctx.save();
    ctx.strokeStyle = "#2a8c57";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(tx.toCanvasX(plot.lip.left), tx.toCanvasY(plot.lip.y));
    ctx.lineTo(tx.toCanvasX(plot.lip.right), tx.toCanvasY(plot.lip.y));
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.strokeStyle = "#d87122";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(tx.toCanvasX(plot.target.left), tx.toCanvasY(plot.target.y));
    ctx.lineTo(tx.toCanvasX(plot.target.right), tx.toCanvasY(plot.target.y));
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.strokeStyle = "#b1442f";
    ctx.lineWidth = 2.5;
    const sensorX = tx.toCanvasX(plot.sensor.x);
    const sensorY = tx.toCanvasY(plot.sensor.y);
    ctx.beginPath();
    ctx.moveTo(sensorX - 8, sensorY - 8);
    ctx.lineTo(sensorX + 8, sensorY + 8);
    ctx.moveTo(sensorX - 8, sensorY + 8);
    ctx.lineTo(sensorX + 8, sensorY - 8);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.fillStyle = "rgba(25, 86, 165, 0.72)";
    plot.points.forEach((point) => {
      const px = tx.toCanvasX(point.x);
      const py = tx.toCanvasY(point.y);
      ctx.beginPath();
      ctx.arc(px, py, 2.4, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.restore();

    drawPlotOverlay(ctx, rect, state);

    pointCounterEl.textContent = `${plot.pointCount} live points, showing ${plot.renderedPointCount}`;
  }

  function drawPlotOverlay(ctx, rect, state) {
    const lines = [];
    if (state.metrics?.liveForwardReturnMm != null) {
      lines.push(`Forward: ${Number(state.metrics.liveForwardReturnMm).toFixed(1)} mm`);
    } else {
      lines.push("Forward: no live hit");
    }

    if (state.gps?.hasFix && state.gps?.latitude != null && state.gps?.longitude != null) {
      lines.push(`Lat: ${Number(state.gps.latitude).toFixed(6)}`);
      lines.push(`Lon: ${Number(state.gps.longitude).toFixed(6)}`);
      lines.push(`GPS: fix, sats ${state.gps.satellites ?? "n/a"}`);
    } else {
      lines.push(`GPS: ${state.gps?.status || "unavailable"}`);
    }

    const boxWidth = 252;
    const lineHeight = 18;
    const boxHeight = 18 + lines.length * lineHeight + 12;
    const x = rect.width - boxWidth - 18;
    const y = 18;

    ctx.save();
    ctx.fillStyle = "rgba(255, 253, 248, 0.92)";
    ctx.strokeStyle = "rgba(216, 208, 191, 0.92)";
    ctx.lineWidth = 1.2;
    roundRect(ctx, x, y, boxWidth, boxHeight, 14);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#2a2a24";
    ctx.font = "13px sans-serif";
    lines.forEach((line, index) => {
      ctx.fillText(line, x + 14, y + 24 + index * lineHeight);
    });
    ctx.restore();
  }

  function roundRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }

  async function pollState(force = false) {
    if (pollInFlight && !force) {
      return;
    }
    pollInFlight = true;

    try {
      const response = await fetch(stateUrl, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      lastState = await response.json();
      modeBadgeEl.textContent = lastState.mode || bootstrap.mode || "Demo";
      configPathEl.textContent = lastState.configPath || bootstrap.configPath || "";
      setStatus(lastState.statusMessage);
      setWorkerError(lastState.workerError);
      syncControls(lastState.parameterValues);
      syncToolbar(lastState);
      renderMetrics(lastState.metrics);
      renderHardware(lastState);
      drawScene(lastState);
    } catch (error) {
      setStatus(`State update failed: ${error.message}`);
    } finally {
      pollInFlight = false;
    }
  }

  async function loadSchema() {
    const response = await fetch(schemaUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    schema = await response.json();
    renderSchema();
  }

  async function start() {
    reloadButtonEl.addEventListener("click", reloadToml);
    clearPointsButtonEl.addEventListener("click", clearPoints);
    lidarPowerButtonEl.addEventListener("click", toggleLidarPower);
    closeDemoButtonEl.addEventListener("click", closeDemo);
    searchInputEl.addEventListener("input", () => {
      filterParameters(searchInputEl.value);
    });

    window.addEventListener("resize", () => {
      if (lastState) {
        drawScene(lastState);
      }
    });

    await loadSchema();
    await pollState(true);
    window.setInterval(() => {
      pollState(false);
    }, 250);
  }

  start().catch((error) => {
    setStatus(`Browser UI failed to start: ${error.message}`);
  });
})();
