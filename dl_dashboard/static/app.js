/* dl-workflow 控制台：SSE 驱动，左侧工作流栏 + 右侧详情（步骤时间轴）。 */
"use strict";

const sel = { project: null, name: null, nodeFilter: null };
const $ = (id) => document.getElementById(id);

async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtTok(n) {
  if (n == null) return "-";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function banner(text) {
  const b = $("banner");
  if (text) { b.textContent = text; b.classList.remove("hidden"); }
  else b.classList.add("hidden");
}

function isWaiting(w) {
  return w.need_user || (w.held_for_gate && w.gate === "pending");
}

function selectWorkflow(project, name) {
  sel.project = project; sel.name = name; sel.nodeFilter = null;
  $("detail-empty").classList.add("hidden");
  $("detail-view").classList.remove("hidden");
  refreshDetail();
}

function renderSidebar(workflows) {
  const box = $("wf-list");
  box.innerHTML = "";
  const waiting = [];
  for (const w of workflows) {
    const item = document.createElement("div");
    item.className = "wf-item";
    if (w.error) item.classList.add("err");
    if (sel.project === w.project && sel.name === w.name) item.classList.add("sel");
    const dot = w.error ? "err" : isWaiting(w) ? "wait" : w.driver_pid ? "ok" : "off";
    item.innerHTML =
      `<div class="wf-line1"><span class="dot ${dot}"></span>` +
      `<span class="wf-name">${esc(w.name)}</span></div>` +
      `<div class="wf-line2"><span class="num">${w.error ? "状态不可读" : esc(w.node)}</span>` +
      `<span class="num">$${esc(w.totals.cost_usd)}</span></div>`;
    item.onclick = () => selectWorkflow(w.project, w.name);
    box.appendChild(item);
    if (isWaiting(w)) waiting.push(`${w.name} @ ${w.node}`);
  }
  if (!workflows.length) {
    box.innerHTML = `<div class="side-empty">暂无工作流，点右上「新建工作流」开始</div>`;
  }
  $("wf-count").textContent = workflows.length ? `${workflows.length} 个` : "";
  // 首次进入自动选中：有待处理的选第一个待处理，否则选第一个
  if (!sel.project && workflows.length) {
    const w = workflows.find(isWaiting) || workflows[0];
    selectWorkflow(w.project, w.name);
  }
  if (waiting.length) {
    banner(`等待处理：${waiting.join("、")}`);
    document.title = `(●) dl-workflow 控制台`;
  } else {
    banner(null);
    document.title = "dl-workflow 控制台";
  }
}

function renderNodes(nodes) {
  const strip = $("node-strip");
  strip.innerHTML = "";
  for (const n of nodes) {
    const chip = document.createElement("span");
    chip.className = `chip ${n.status}`;
    chip.textContent = `${n.node_id} ${n.label}`;
    if (sel.nodeFilter === n.node_id) chip.classList.add("active");
    chip.onclick = () => {
      sel.nodeFilter = sel.nodeFilter === n.node_id ? null : n.node_id;
      refreshDetail();
    };
    strip.appendChild(chip);
  }
}

/* 步骤时间轴（甘特泳道）：节点为道、段为真实时间定位的横条。
   x 轴 = 真实墙钟时间（段 ts 起、duration_s 长），顶部刻度 + 竖网格线 + now 虚线；
   泳道标签 sticky 钉左；当前节点泳道 sky。横向可滑动（拖拽 + 滚轮）。 */
function renderTimeline(stats, nodes, info) {
  const box = $("timeline");
  box.innerHTML = "";
  const segs = stats.filter((s) => s.ts);
  if (!segs.length) {
    box.innerHTML = `<div class="tl-empty">无步骤数据</div>`;
    $("tl-summary").textContent = "";
    return;
  }
  const t0 = Math.min(...segs.map((s) => new Date(s.ts).getTime()));
  const now = Date.now();
  let t1 = Math.max(...segs.map((s) => new Date(s.ts).getTime() + (s.duration_s || 0) * 1000));
  if (now > t1) t1 = now;
  const span = Math.max((t1 - t0) / 1000, 60);
  const scale = Math.max(0.5, 900 / span);  // px/秒，轨道总宽 ≥900px
  const LABEL_W = 150;
  const railW = Math.ceil(span * scale);

  const fmtT = (ms) => {
    const d = new Date(ms);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return span > 86400 ? `${d.getMonth() + 1}-${d.getDate()} ${hh}:${mm}` : `${hh}:${mm}`;
  };
  const fmtDur = (s) => s == null ? "-" : s;

  const root = document.createElement("div");
  root.className = "gt";
  root.style.width = LABEL_W + railW + "px";

  // 顶部时间刻度 + 竖网格线
  const axis = document.createElement("div");
  axis.className = "gt-axis";
  const NTICK = 5;
  for (let i = 0; i <= NTICK; i++) {
    const ms = t0 + (span * 1000 * i) / NTICK;
    const x = LABEL_W + Math.round(((ms - t0) / 1000) * scale);
    const tick = document.createElement("span");
    tick.className = "gt-tick num";
    tick.style.left = x + "px";
    tick.textContent = fmtT(ms);
    axis.appendChild(tick);
    if (i > 0 && i < NTICK) {
      const gl = document.createElement("div");
      gl.className = "gt-gridline";
      gl.style.left = x + "px";
      root.appendChild(gl);
    }
  }
  root.appendChild(axis);

  // 泳道：按 phase 分组、节点表顺序，只画有段的节点
  const byNode = new Map();
  for (const s of segs) {
    if (!byNode.has(s.node)) byNode.set(s.node, []);
    byNode.get(s.node).push(s);
  }
  let lastPhase = null;
  for (const n of nodes) {
    const nodeSegs = byNode.get(n.node_id);
    if (!nodeSegs) continue;
    if (n.phase !== lastPhase) {
      lastPhase = n.phase;
      const ph = document.createElement("div");
      ph.className = "gt-phase";
      ph.textContent = n.phase;
      root.appendChild(ph);
    }
    const lane = document.createElement("div");
    lane.className = "gt-lane" + (n.status === "current" ? " cur" : "");
    if (sel.nodeFilter && n.node_id !== sel.nodeFilter) lane.classList.add("dim");
    const label = document.createElement("div");
    label.className = "gt-label";
    label.innerHTML = `<span class="num">${esc(n.node_id)}</span> ${esc(n.label)}`;
    lane.appendChild(label);
    const rail = document.createElement("div");
    rail.className = "gt-rail";
    for (const s of nodeSegs) {
      const x = Math.round(((new Date(s.ts).getTime() - t0) / 1000) * scale);
      const isCur = n.status === "current";
      const bar = document.createElement("div");
      if (s.duration_s == null) {
        bar.className = "gt-mark";
        bar.style.left = x + "px";
        bar.title = `${s.node}#${s.sub_step}\n${s.ts} · 无统计数据`;
      } else {
        bar.className = "gt-bar" + (isCur ? " cur" : "");
        bar.style.left = x + "px";
        bar.style.width = Math.max(3, Math.round(s.duration_s * scale)) + "px";
        bar.title =
          `${s.node}#${s.sub_step}\n${s.ts} 起 · 耗时 ${s.duration_s}s · ` +
          `${fmtDur(s.num_turns)} 轮\ntok in ${s.input_tokens ?? "-"} / out ` +
          `${s.output_tokens ?? "-"}\n$${(s.cost_usd ?? 0).toFixed(3)}`;
        if (s.duration_s * scale > 68) {
          bar.textContent = `#${s.sub_step} ${s.duration_s}s·${fmtDur(s.num_turns)}轮`;
        }
      }
      rail.appendChild(bar);
    }
    lane.appendChild(rail);
    root.appendChild(lane);
  }

  // now 虚线
  const nowLine = document.createElement("div");
  nowLine.className = "gt-now";
  nowLine.style.left = LABEL_W + Math.round(((now - t0) / 1000) * scale) + "px";
  nowLine.title = "现在";
  root.appendChild(nowLine);

  box.appendChild(root);
  // 拖拽滑动（grab to scroll）
  let dragging = false, startX = 0, startLeft = 0;
  box.onpointerdown = (e) => {
    dragging = true; startX = e.clientX; startLeft = box.scrollLeft;
    box.classList.add("grabbing");
  };
  box.onpointermove = (e) => {
    if (!dragging) return;
    box.scrollLeft = startLeft - (e.clientX - startX);
  };
  const stop = () => { dragging = false; box.classList.remove("grabbing"); };
  box.onpointerup = box.onpointerleave = stop;
  box.onwheel = (e) => {
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      box.scrollLeft += e.deltaY;
      e.preventDefault();
    }
  };
  const totTurns = segs.reduce((a, s) => a + (s.num_turns || 0), 0);
  const totDur = segs.reduce((a, s) => a + (s.duration_s || 0), 0);
  const totCost = segs.reduce((a, s) => a + (s.cost_usd || 0), 0);
  $("tl-summary").textContent =
    `${segs.length} 段 · ${totTurns} 轮 · ${totDur}s · $${totCost.toFixed(2)}`;
}

function renderInteract(d) {
  const box = $("interact");
  box.innerHTML = "";
  const proj = sel.project, name = sel.name;
  const mkBtn = (label, fn, cls) => {
    const b = document.createElement("button");
    b.textContent = label; b.onclick = fn;
    b.className = cls || "btn";
    return b;
  };
  if (d.need_user && d.need_user.questions) {
    const h = document.createElement("h3");
    h.textContent = "等待输入";
    box.appendChild(h);
    const answers = [];
    d.need_user.questions.forEach((q, i) => {
      const div = document.createElement("div");
      div.className = "q";
      div.innerHTML = `<b>[${esc(q.header || "Q" + (i + 1))}]</b> ${esc(q.question)}`;
      (q.options || []).forEach((op) => {
        const l = document.createElement("label");
        l.innerHTML =
          `<input type="radio" name="q${i}" value="${esc(op.label)}"> ` +
          `<b>${esc(op.label)}</b> · ${esc(op.description || "")}`;
        div.appendChild(l);
      });
      const other = document.createElement("input");
      other.placeholder = "或直接输入答案";
      other.id = `q${i}-other`;
      div.appendChild(other);
      box.appendChild(div);
      answers.push(i);
    });
    box.appendChild(mkBtn("提交答案", async () => {
      const parts = answers.map((i) => {
        const checked = document.querySelector(`input[name=q${i}]:checked`);
        const other = $(`q${i}-other`).value.trim();
        return `问题${i + 1}：${other || (checked ? checked.value : "（未选）")}`;
      });
      const r = await post("/api/inject",
        { project: proj, name, answer: parts.join("\n") });
      alert(r.msg);
      refreshDetail();
    }, "btn primary"));
  }
  if (d.info.held_for_gate || d.info.gate === "pending") {
    box.appendChild(mkBtn("gate 放行", async () => {
      const r = await post("/api/gate", { project: proj, name });
      alert(r.msg); refreshDetail();
    }, "btn primary"));
  }
  if (!d.driver_pid) {
    box.appendChild(mkBtn("重新驱动", async () => {
      const r = await post("/api/drive", { project: proj, name });
      alert(r.msg); refreshDetail();
    }));
  }
  const form = document.createElement("span");
  form.className = "dl-form";
  form.innerHTML =
    `<select id="dl-cmd"><option>advance</option><option>step-pass</option>` +
    `<option>next</option><option>back</option><option>jump</option>` +
    `<option>dispute</option><option>state-reset</option></select>` +
    `<input id="dl-value" placeholder="参数（可空）" size="18">`;
  const go = mkBtn("执行 /dl", async () => {
    const r = await post("/api/dl", { project: proj, name,
      cmd: $("dl-cmd").value, value: $("dl-value").value || null });
    alert(r.msg); refreshDetail();
  });
  box.appendChild(form); box.appendChild(go);
}

function renderSegs(stats) {
  const tb = document.querySelector("#seg-table tbody");
  tb.innerHTML = "";
  let shown = 0;
  for (const s of stats) {
    if (sel.nodeFilter && s.node !== sel.nodeFilter) continue;
    shown++;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td class="num">${esc(s.node)}</td><td class="num">${esc(s.sub_step)}</td><td>${esc(s.kind)}</td>` +
      `<td class="num">${esc(s.num_turns ?? "-")}</td><td class="num">${esc(s.duration_s ?? "-")}</td>` +
      `<td class="num">${esc(fmtTok(s.input_tokens))}</td><td class="num">${esc(fmtTok(s.output_tokens))}</td>` +
      `<td class="num">${esc(s.cost_usd ?? "-")}</td><td class="num">${esc(s.ts)}</td><td>${esc(s.note)}</td>`;
    tb.appendChild(tr);
  }
  if (!shown) {
    tb.innerHTML = `<tr class="empty"><td colspan="10">无段记录</td></tr>`;
  }
  $("seg-count").textContent = shown ? `${shown} 段` : "";
}

async function refreshDetail() {
  if (!sel.project) return;
  const r = await fetch(
    `/api/workflow?project=${encodeURIComponent(sel.project)}` +
    `&name=${encodeURIComponent(sel.name)}`);
  const d = await r.json();
  $("d-title").textContent = `${d.info.name} · ${d.info.node}` +
    (d.driver_pid ? `（driver #${d.driver_pid}）` : "（driver 已停）");
  $("d-statement").textContent = d.info.problem_statement;
  renderTimeline(d.stats, d.info.nodes, d.info);
  renderNodes(d.info.nodes);
  renderInteract(d);
  renderSegs(d.stats);
  $("log-tail").textContent = d.log_tail;
}

$("create-toggle").onclick = () => $("create-form").classList.toggle("hidden");

$("create-form").onsubmit = async (e) => {
  e.preventDefault();
  const r = await post("/api/create", {
    project: $("cf-project").value.trim(),
    name: $("cf-name").value.trim(),
    statement: $("cf-statement").value.trim(),
  });
  alert(r.msg);
};

const es = new EventSource("/api/events");
es.onmessage = (e) => {
  const data = JSON.parse(e.data);
  renderSidebar(data.workflows);
  if (sel.project) refreshDetail();
};
