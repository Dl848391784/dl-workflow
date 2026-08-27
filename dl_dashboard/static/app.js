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

/* 步骤时间轴（树形）：major_state 分带 -> minor_state 为枝 -> step 为叶。
   枝从节点头垂下茎线，叶以横枝挂在茎上；已执行叶显示 耗时/轮数/tok/成本，
   当前步 sky 脉冲，未执行叶灰色占位。横向可滑动（拖拽 + 滚轮）。 */
function renderTimeline(stats, nodes, info) {
  const box = $("timeline");
  box.innerHTML = "";
  const stepMap = new Map();
  for (const s of stats) {
    const key = `${s.node}#${s.sub_step}`;
    if (!stepMap.has(key)) {
      stepMap.set(key, { dur: 0, turns: 0, tin: 0, tout: 0, cost: 0 });
    }
    const a = stepMap.get(key);
    a.dur += s.duration_s || 0;
    a.turns += s.num_turns || 0;
    a.tin += s.input_tokens || 0;
    a.tout += s.output_tokens || 0;
    a.cost += s.cost_usd || 0;
  }
  const phases = [];
  for (const n of nodes) {
    let ph = phases.find((p) => p.name === n.phase);
    if (!ph) { ph = { name: n.phase, nodes: [] }; phases.push(ph); }
    ph.nodes.push(n);
  }
  if (!phases.length) {
    box.innerHTML = `<div class="tl-empty">无步骤数据</div>`;
    $("tl-summary").textContent = "";
    return;
  }
  const track = document.createElement("div");
  track.className = "tl-track";
  for (const ph of phases) {
    const doneCount = ph.nodes.filter((n) => n.status === "done").length;
    const phEl = document.createElement("div");
    phEl.className = "tl-phase";
    phEl.innerHTML =
      `<div class="tl-phase-head">${esc(ph.name)}` +
      `<span class="num">${doneCount}/${ph.nodes.length}</span></div>`;
    const branches = document.createElement("div");
    branches.className = "tl-branches";
    for (const n of ph.nodes) {
      // 节点内耗时最大值：叶内迷你条的比例尺
      let nodeMax = 1;
      for (let i = 1; i <= n.sub_total; i++) {
        const a = stepMap.get(`${n.node_id}#${i}`);
        if (a && a.dur > nodeMax) nodeMax = a.dur;
      }
      const nodeEl = document.createElement("div");
      nodeEl.className = `tl-node ${n.status}`;
      if (sel.nodeFilter && n.node_id !== sel.nodeFilter) nodeEl.classList.add("dim");
      const head = document.createElement("div");
      head.className = "tl-node-head";
      head.innerHTML = `<span class="num">${esc(n.node_id)}</span> ${esc(n.label)}`;
      nodeEl.appendChild(head);
      const leaves = document.createElement("div");
      leaves.className = "tl-leaves";
      for (let i = 1; i <= n.sub_total; i++) {
        const key = `${n.node_id}#${i}`;
        const a = stepMap.get(key);
        const isCur = n.status === "current" && i === info.sub_step_index;
        const leaf = document.createElement("div");
        leaf.className = "tl-leaf" + (a ? " done" : isCur ? " cur" : " todo");
        if (a) {
          const barW = Math.max(2, Math.round((a.dur / nodeMax) * 90));
          leaf.title =
            `${key}\n耗时 ${a.dur}s · ${a.turns} 轮\n` +
            `tok in ${a.tin} / out ${a.tout}\n$${a.cost.toFixed(3)}`;
          leaf.innerHTML =
            `<div class="tl-l1"><span class="tl-lid num">#${i}</span>` +
            `<span class="tl-bar" style="width:${barW}px"></span>` +
            `<span class="tl-ldur num">${a.dur}s</span></div>` +
            `<div class="tl-l2 num">${a.turns}轮 ` +
            `in${fmtTok(a.tin)}/out${fmtTok(a.tout)} ` +
            `$${a.cost.toFixed(2)}</div>`;
        } else {
          leaf.innerHTML = `<div class="tl-l1"><span class="tl-lid num">#${i}</span></div>`;
        }
        leaves.appendChild(leaf);
      }
      nodeEl.appendChild(leaves);
      branches.appendChild(nodeEl);
    }
    phEl.appendChild(branches);
    track.appendChild(phEl);
  }
  box.appendChild(track);
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
  const totTurns = [...stepMap.values()].reduce((a, r) => a + r.turns, 0);
  const totDur = [...stepMap.values()].reduce((a, r) => a + r.dur, 0);
  const totCost = [...stepMap.values()].reduce((a, r) => a + r.cost, 0);
  $("tl-summary").textContent =
    `${stepMap.size} 步已执行 · ${totTurns} 轮 · ${totDur}s · $${totCost.toFixed(2)}`;
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
