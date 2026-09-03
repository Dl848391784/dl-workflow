/* 系统健康页（evolution-up P2）：跨实例三榜，数据 = GET /api/health。 */
"use strict";

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function tbl(head, rows) {
  if (!rows.length) return '<div class="hint">暂无数据</div>';
  return '<table class="audit-tbl"><thead><tr>' +
    head.map((h) => `<th>${h}</th>`).join("") +
    "</tr></thead><tbody>" + rows.join("") + "</tbody></table>";
}

async function load() {
  const r = await fetch("/api/health");
  const d = await r.json();
  $("health-meta").textContent =
    `覆盖 ${d.instances} 个实例` +
    (d.errors.length ? ` · ${d.errors.length} 个坏实例已隔离（见页底）` : "");
  $("gate-board").innerHTML = tbl(
    ["步骤", "判决实例", "判决总次", "block", "block 率"],
    d.gate_board.map((b) =>
      `<tr class="${b.blocked ? "audit-blocked" : "audit-pass"}">` +
      `<td class="num">${esc(b.step)}</td><td class="num">${b.judged}</td>` +
      `<td class="num">${b.verdicts}</td><td class="num">${b.blocked}</td>` +
      `<td class="num">${(b.block_rate * 100).toFixed(0)}%</td></tr>`));
  $("node-costs").innerHTML = tbl(
    ["节点", "实例", "总成本", "p50 成本", "p90 成本", "p50 墙钟", "p90 墙钟"],
    d.node_costs.map((n) =>
      `<tr><td class="num">${esc(n.node)}</td><td class="num">${n.instances}</td>` +
      `<td class="num">$${n.total_cost}</td><td class="num">$${n.p50_cost}</td>` +
      `<td class="num">$${n.p90_cost}</td>` +
      `<td class="num">${n.p50_duration_s}s</td><td class="num">${n.p90_duration_s}s</td></tr>`));
  $("dispute-board").innerHTML = tbl(
    ["步骤", "申诉次数"],
    d.dispute_board.map((b) =>
      `<tr><td class="num">${esc(b.step)}</td><td class="num">${b.count}</td></tr>`));
  if (d.errors.length) {
    $("health-errors").innerHTML =
      '<div class="section-head"><h2>坏实例（已隔离）</h2></div><ul>' +
      d.errors.map((e) =>
        `<li><span class="num">${esc(e.project)}/${esc(e.name)}</span> ${esc(e.error)}</li>`
      ).join("") + "</ul>";
  }
}

load();
