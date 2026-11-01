const form = document.querySelector("#query-form");
const statusBox = document.querySelector("#status");
const results = document.querySelector("#results");
const chart = document.querySelector("#chart");
const citationPanel = document.querySelector("#citation-panel");
const scrim = document.querySelector("#scrim");
let latestResponse = null;
let latestRequest = null;
let latestPlanType = null;
let latestCitationSelection = null;

loadSharedQuery();

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelector("#query").value = chip.dataset.query;
    latestPlanType = chip.dataset.type;
    form.requestSubmit();
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const payload = Object.fromEntries([...formData.entries()].filter(([, value]) => value !== ""));
  payload.query = String(payload.query || "").trim();
  if (latestPlanType) payload.analysis_type = latestPlanType;
  else delete payload.analysis_type;
  ["start_year", "end_year", "max_trials"].forEach((key) => {
    if (payload[key]) payload[key] = Number(payload[key]);
  });
  const button = form.querySelector(".submit-button");
  button.disabled = true;
  results.classList.add("hidden");
  showStatus("loading", "Searching ClinicalTrials.gov and preparing your visualization…");
  try {
    const response = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      const error = body.error || {};
      throw new Error(error.message || `Request failed (${response.status})`);
    }
    latestResponse = body;
    latestRequest = { ...payload };
    document.querySelector("#download-csv").disabled = false;
    document.querySelector("#share-query").disabled = false;
    statusBox.classList.add("hidden");
    results.classList.remove("hidden");
    await new Promise((resolve) => requestAnimationFrame(resolve));
    renderResults(body);
  } catch (error) {
    showStatus("error", error.message || "The query could not be completed.");
  } finally {
    button.disabled = false;
    latestPlanType = null;
  }
});

function showStatus(kind, message) {
  statusBox.className = `status ${kind}`;
  statusBox.innerHTML = kind === "loading"
    ? `<span class="spinner"></span><span>${escapeHtml(message)}</span>`
    : escapeHtml(message);
}

function renderResults(response) {
  const { visualization: viz, meta } = response;
  latestCitationSelection = null;
  document.querySelector("#reopen-citations").classList.add("hidden");
  document.querySelector("#chart-title").textContent = viz.title;
  document.querySelector("#interpretation").textContent = meta.query_interpretation;
  document.querySelector("#metrics").innerHTML = `
    <div class="metric"><strong>${formatNumber(meta.trials_analyzed)}</strong><span>trials fetched</span></div>
    <div class="metric"><strong>${formatNumber(meta.total_matching)}</strong><span>matching in registry${meta.truncated ? " · capped" : ""}</span></div>
    <div class="metric"><strong>${meta.counts_exact ? "Exact" : "Sample"}</strong><span>${meta.counts_exact ? "registry counts" : "counts · see warning"}</span></div>
    <div class="metric"><strong>${formatNumber(meta.total_citations)}</strong><span>source citations</span></div>
    <div class="metric"><strong>${meta.planner_mode === "llm" ? "AI plan" : "manual plan"}</strong><span>query interpretation</span></div>`;
  const filters = Object.entries(meta.filters_applied || {});
  document.querySelector("#filter-summary").innerHTML = filters.length
    ? filters.map(([key, value]) => `<span class="filter-tag">${escapeHtml(key.replaceAll("_", " "))}: ${escapeHtml(value)}</span>`).join("")
    : '<span class="muted">No structured filters</span>';
  document.querySelector("#warnings").innerHTML = (meta.warnings || []).map((warning) => `<div class="warning">${escapeHtml(warning)}</div>`).join("");
  document.querySelector("#generated").textContent = `Generated ${new Date(meta.generated_at).toLocaleString()} · ${meta.source}`;
  document.querySelector("#json-view").textContent = JSON.stringify(response, null, 2);
  document.querySelector("#json-view").classList.add("hidden");
  document.querySelector("#json-toggle").textContent = "View JSON";
  renderVisualization(viz);
}

function renderVisualization(viz) {
  chart.replaceChildren();
  if (viz.type === "network_graph") {
    renderNetwork(viz);
    return;
  }
  if (!viz.data?.length) {
    chart.innerHTML = '<div class="muted" style="padding:80px 20px;text-align:center">No chart data matched this query. Try broadening the filters.</div>';
    return;
  }
  const mark = viz.type === "time_series" ? "line" : viz.type === "scatter_plot" ? "point" : "bar";
  const encoding = {};
  for (const channel of ["x", "xOffset", "y", "color"]) {
    if (viz.encoding[channel]) encoding[channel] = { ...viz.encoding[channel] };
  }
  if (viz.encoding.sort && encoding.x) encoding.x.sort = viz.encoding.sort;
  if (viz.encoding.tooltip?.length) {
    encoding.tooltip = viz.encoding.tooltip
      .filter((field) => viz.data.some((row) => field in row))
      .map((field) => ({ field, type: typeof viz.data[0][field] === "number" ? "quantitative" : "nominal" }));
  }
  const selectionFields = viz.type === "scatter_plot"
    ? ["nct_id"]
    : viz.type === "grouped_bar_chart"
      ? ["category", "group"]
      : [viz.data[0]?.year !== undefined ? "year" : viz.encoding.x.field];
  const specification = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    width: "container",
    height: 300,
    data: { values: viz.data },
    mark: {
      type: mark,
      tooltip: true,
      cursor: "pointer",
      ...(mark === "bar" ? { cornerRadiusTopLeft: 3, cornerRadiusTopRight: 3 } : {}),
      ...(mark === "line" ? { point: true } : {}),
    },
    encoding,
    params: [{ name: "datum_click", select: { type: "point", on: "click", clear: "dblclick", fields: selectionFields } }],
    config: {
      background: "transparent",
      view: { stroke: null },
      axis: { labelColor: "#76847b", titleColor: "#65766b", gridColor: "#edf1ed", domain: false, tickColor: "#edf1ed", labelFont: "DM Sans", titleFont: "DM Sans" },
      bar: { color: "#4b8061" },
      line: { color: "#4b8061", strokeWidth: 3, point: { filled: true, size: 55, color: "#4b8061" } },
      point: { filled: true, size: 70, opacity: 0.7, color: "#4b8061" },
    },
  };
  vegaEmbed(chart, specification, { actions: false, renderer: "svg" }).then(({ view }) => {
    view.addEventListener("click", (_event, item) => {
      if (item?.datum) {
        openCitations(
          item.datum,
          item.datum.category || item.datum.group || item.datum.country || item.datum.year || item.datum.nct_id || "Selected datum",
        );
      }
    });
    view.addSignalListener("datum_click", (_name, selection) => {
      const fields = selection?.fields || [];
      const values = selection?.values || [];
      if (!fields.length) return;
      const datum = viz.data.find((row) => fields.every((item, index) => {
        const selected = values[index];
        const value = row[item.field];
        return item.type === "E" ? String(value).toLowerCase() === String(selected).toLowerCase() : value === selected;
      }));
      if (datum) openCitations(datum, datum.category || datum.group || datum.year || datum.nct_id || "Selected datum");
    });
  }).catch((error) => {
    showStatus("error", `Visualization could not be rendered: ${error.message}`);
  });
}

function renderNetwork(viz) {
  const nodes = (viz.nodes || []).map((node) => ({ ...node }));
  const edges = (viz.edges || []).map((edge) => ({ ...edge }));
  if (!nodes.length) {
    chart.innerHTML = '<div class="muted" style="padding:80px 20px;text-align:center">No relationships met the graph thresholds. Try more trials or broaden the query.</div>';
    return;
  }
  const width = Math.max(320, chart.clientWidth || 700);
  const height = 390;
  const svg = d3.select(chart).append("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("role", "img").attr("aria-label", viz.title);
  const root = svg.append("g");
  svg.call(d3.zoom().scaleExtent([0.35, 3]).on("zoom", (event) => root.attr("transform", event.transform)));
  const colors = { sponsor: "#3d7255", drug: "#e18b52", condition: "#7189a6" };
  const maxWeight = d3.max(nodes, (node) => node.weight) || 1;
  root.append("g").selectAll("line").data(edges).join("line")
    .attr("stroke", "#b6c8ba").attr("stroke-opacity", 0.7).attr("stroke-width", (edge) => Math.min(7, 1 + edge.weight * 0.7))
    .style("cursor", "pointer")
    .on("click", (_event, edge) => openCitations(edge, `${nodeLabel(nodes, edge.source)} ↔ ${nodeLabel(nodes, edge.target)} · ${edge.weight} trials`))
    .append("title").text((edge) => `${edge.weight} co-occurring trials`);
  const linkSelection = root.select("g").selectAll("line");
  const node = root.append("g").selectAll("g").data(nodes).join("g").attr("class", "graph-node").style("cursor", "pointer")
    .call(d3.drag().on("start", dragStarted).on("drag", dragged).on("end", dragEnded))
    .on("click", (_event, datum) => openCitations(datum, datum.label));
  node.append("circle")
    .attr("r", (datum) => 7 + 12 * Math.sqrt(datum.weight / maxWeight))
    .attr("fill", (datum) => colors[datum.type] || "#7189a6")
    .attr("fill-opacity", 0.9).attr("stroke", "#fff").attr("stroke-width", 2);
  node.append("text").text((datum) => datum.label).attr("x", 12).attr("y", 4).attr("font-size", 10).attr("fill", "#405447")
    .each(function(datum) { if (datum.label.length > 28) d3.select(this).text(`${datum.label.slice(0, 26)}…`); });
  node.append("title").text((datum) => `${datum.label} · ${datum.type} · ${datum.weight} trials`);
  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id((datum) => datum.id).distance(100).strength(0.55))
    .force("charge", d3.forceManyBody().strength(-250))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide().radius((datum) => 22 + 12 * Math.sqrt(datum.weight / maxWeight)));
  simulation.on("tick", () => {
    linkSelection.attr("x1", (edge) => edge.source.x).attr("y1", (edge) => edge.source.y)
      .attr("x2", (edge) => edge.target.x).attr("y2", (edge) => edge.target.y);
    node.attr("transform", (datum) => `translate(${datum.x},${datum.y})`);
  });
  function dragStarted(event, datum) { if (!event.active) simulation.alphaTarget(0.3).restart(); datum.fx = datum.x; datum.fy = datum.y; }
  function dragged(event, datum) { datum.fx = event.x; datum.fy = event.y; }
  function dragEnded(event, datum) { if (!event.active) simulation.alphaTarget(0); datum.fx = null; datum.fy = null; }
}

function nodeLabel(nodes, node) { return nodes.find((item) => item.id === (typeof node === "string" ? node : node.id))?.label || "Study"; }

function openCitations(datum, label) {
  latestCitationSelection = { datum, label };
  document.querySelector("#reopen-citations").classList.remove("hidden");
  showCitationSelection(datum, label);
}

function datumLabel(datum, viz) {
  if (viz.type === "network_graph") {
    if (datum.source !== undefined) {
      return `${nodeLabel(viz.nodes || [], datum.source)} ↔ ${nodeLabel(viz.nodes || [], datum.target)}`;
    }
    return datum.label;
  }
  if (datum.group !== undefined) return `${datum.group} · ${datum.category}`;
  if (datum.bin_start !== undefined) return `${formatNumber(datum.bin_start)}–${formatNumber(datum.bin_end)} participants`;
  if (datum.nct_id && viz.type === "scatter_plot") return `${datum.nct_id} · ${datum.title || ""}`;
  return String(datum.category ?? datum.country ?? datum.year ?? datum.nct_id ?? "Data point");
}

function showOverview() {
  const viz = latestResponse?.visualization;
  if (!viz) return;
  latestCitationSelection = null;
  document.querySelector("#citation-title").textContent = "All data points";
  const item = (datum, count) => `
    <li><button type="button" data-index="${datum.__index}">${escapeHtml(datumLabel(datum, viz))}<span class="datum-count">${formatNumber(count)} trials ›</span></button></li>`;
  const sections = viz.type === "network_graph"
    ? [["NODES", viz.nodes || [], (d) => d.weight], ["CONNECTIONS", viz.edges || [], (d) => d.weight]]
    : [["", viz.data || [], (d) => d.trial_count]];
  const entries = [];
  const html = sections.map(([heading, rows, count]) => {
    if (!rows.length) return "";
    const list = rows.map((datum) => {
      entries.push(datum);
      return item({ ...datum, __index: entries.length - 1 }, count(datum));
    }).join("");
    return `${heading ? `<p class="datum-group">${heading}</p>` : ""}<ul class="datum-list">${list}</ul>`;
  }).join("");
  const content = document.querySelector("#citation-content");
  content.innerHTML = `<p class="muted">Choose a data point to see the trials and exact registry fields behind it.</p>${html || '<p class="muted">This visualization has no data points.</p>'}`;
  content.querySelectorAll("[data-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const datum = entries[Number(button.dataset.index)];
      latestCitationSelection = { datum, label: datumLabel(datum, viz) };
      showCitationSelection(datum, latestCitationSelection.label);
    });
  });
  citationPanel.classList.add("open");
  scrim.classList.add("open");
}

function showCitationSelection(datum, label) {
  const citations = datum.citations || [];
  const nctIds = [...new Set(datum.nct_ids || [])];
  document.querySelector("#citation-title").textContent = label;
  const content = document.querySelector("#citation-content");
  const back = '<button type="button" class="back-link" id="back-to-overview">← All data points</button>';
  const citationCards = citations.length ? citations.map((citation) => `
    <article class="citation-card">
      <a href="https://clinicaltrials.gov/study/${encodeURIComponent(citation.nct_id)}" target="_blank" rel="noreferrer">${escapeHtml(citation.nct_id)} ↗</a>
      <p class="citation-title">${escapeHtml(citation.title || "Clinical study")}</p>
      <div class="citation-field"><span>Source field</span><code>${escapeHtml(citation.field_path)}</code></div>
      <div class="citation-field"><span>Exact API value</span><pre>${escapeHtml(JSON.stringify(citation.exact_value, null, 2))}</pre></div>
    </article>`).join("") : '<p class="muted">No source records were attached to this datum.</p>';
  const allContributors = nctIds.length > citations.length ? `
    <section class="all-contributors">
      <h3>All contributing trials <span>(${formatNumber(nctIds.length)})</span></h3>
      <ul>${nctIds.map((nctId) => `
        <li><a href="https://clinicaltrials.gov/study/${encodeURIComponent(nctId)}" target="_blank" rel="noreferrer">${escapeHtml(nctId)} ↗</a></li>`).join("")}
      </ul>
    </section>` : "";
  const exactNote = datum.count_query_url
    ? `<p class="muted">The registry total (${formatNumber(datum.trial_count)}) comes from <a href="${escapeHtml(datum.count_query_url)}" target="_blank" rel="noreferrer">this ClinicalTrials.gov query ↗</a>; the records below are the ${formatNumber(datum.sample_trial_count)} fetched trials in this bucket.</p>`
    : "";
  content.innerHTML = back + exactNote + citationCards + allContributors;
  document.querySelector("#back-to-overview").addEventListener("click", showOverview);
  citationPanel.classList.add("open");
  scrim.classList.add("open");
}

function closeCitations() { citationPanel.classList.remove("open"); scrim.classList.remove("open"); }
document.querySelector("#close-citations").addEventListener("click", closeCitations);
document.querySelector("#reopen-citations").addEventListener("click", () => {
  if (latestCitationSelection) {
    showCitationSelection(latestCitationSelection.datum, latestCitationSelection.label);
  } else {
    showOverview();
  }
});
scrim.addEventListener("click", closeCitations);
document.querySelector("#json-toggle").addEventListener("click", (event) => {
  const view = document.querySelector("#json-view");
  view.classList.toggle("hidden");
  event.currentTarget.textContent = view.classList.contains("hidden") ? "View JSON" : "Hide JSON";
});
document.querySelector("#download-csv").addEventListener("click", downloadCsv);
document.querySelector("#share-query").addEventListener("click", copyShareLink);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeCitations(); });

function downloadCsv() {
  if (!latestResponse) return;
  const { visualization } = latestResponse;
  const records = visualization.type === "network_graph"
    ? [
      ...(visualization.nodes || []).map((node) => ({ record_type: "node", ...node })),
      ...(visualization.edges || []).map((edge) => ({ record_type: "edge", ...edge })),
    ]
    : visualization.data || [];
  if (!records.length) {
    showStatus("error", "There are no visualization records to export.");
    return;
  }
  const headers = [...new Set(records.flatMap((record) => Object.keys(record)))];
  const csvValue = (value) => {
    const text = value === null || value === undefined
      ? ""
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
    return `"${text.replaceAll('"', '""')}"`;
  };
  const csv = [headers, ...records.map((record) => headers.map((header) => record[header]))]
    .map((row) => row.map(csvValue).join(","))
    .join("\r\n");
  const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = `trial-scope-${latestResponse.meta.plan.analysis_type}.csv`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function copyShareLink() {
  if (!latestResponse || !latestRequest) return;
  const sharedRequest = {
    ...latestRequest,
    analysis_type: latestResponse.meta.plan.analysis_type,
  };
  for (const [field, value] of Object.entries(latestResponse.meta.filters_applied || {})) {
    if (field in sharedRequest || ["drug_name", "condition", "sponsor", "phase", "country", "recruitment_status", "start_year", "end_year"].includes(field)) {
      sharedRequest[field] = value;
    }
  }
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  for (const [key, value] of Object.entries(sharedRequest)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  try {
    await navigator.clipboard.writeText(url.toString());
    showStatus("success", "Query link copied. Opening it will restore the query and filters; submit to run it again.");
  } catch {
    showStatus("error", "Could not copy the query link. Check clipboard permissions and try again.");
  }
}

function loadSharedQuery() {
  const params = new URLSearchParams(window.location.search);
  const fields = ["query", "drug_name", "condition", "sponsor", "phase", "country", "recruitment_status", "start_year", "end_year", "max_trials"];
  let restored = false;
  for (const field of fields) {
    const value = params.get(field);
    const input = form.elements.namedItem(field);
    if (value !== null && input) {
      input.value = value;
      restored = true;
    }
  }
  const analysisType = params.get("analysis_type");
  if (analysisType && ["time_trend", "distribution", "comparison", "geographic", "network", "histogram", "scatter"].includes(analysisType)) {
    latestPlanType = analysisType;
    restored = true;
  }
  if (restored) {
    showStatus("success", "Shared query restored. Review the filters, then select Explore trials to run it.");
  }
}

function formatNumber(value) { return new Intl.NumberFormat().format(value || 0); }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}
