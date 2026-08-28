/* dl-workflow 控制台：SSE 驱动，左侧工作流栏 + 右侧详情（步骤时间轴）。 */
"use strict";

const sel = { project: null, name: null };
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

function isWaiting(w) {
  return w.need_user || (w.held_for_gate && w.gate === "pending");
}

function selectWorkflow(project, name) {
  sel.project = project; sel.name = name;
  $("detail-empty").classList.add("hidden");
  $("detail-view").classList.remove("hidden");
  refreshDetail();
  loadOutputs();
}

function renderSidebar(workflows) {
  const box = $("wf-list");
  box.innerHTML = "";
  for (const w of workflows) {
    const item = document.createElement("div");
    item.className = "wf-item";
    if (w.error) item.classList.add("err");
    if (sel.project === w.project && sel.name === w.name) item.classList.add("sel");
    const dot = w.error ? "err" : isWaiting(w) ? "wait" : w.driver_pid ? "ok" : "off";
    const modeTag = w.force_tacet
      ? `<span class="tag mode-tacet">tacet</span>`
      : w.force_fermate ? `<span class="tag mode-fermate">fermate</span>` : "";
    item.innerHTML =
      `<div class="wf-line1"><span class="dot ${dot}"></span>` +
      `<span class="wf-name">${esc(w.name)}</span>${modeTag}` +
      `<button class="wf-del" title="删除工作流">×</button></div>` +
      `<div class="wf-line2"><span class="num">${w.error ? "状态不可读" : esc(w.node)}</span>` +
      `<span class="num">$${esc(w.totals.cost_usd)}</span></div>`;
    item.onclick = () => selectWorkflow(w.project, w.name);
    item.querySelector(".wf-del").onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(
        `删除工作流 ${w.name}？\n将彻底删除 worktree + 分支 + 元数据，不可恢复。`)) return;
      const r = await post("/api/delete", { project: w.project, name: w.name });
      alert(r.msg);
      if (r.ok && sel.project === w.project && sel.name === w.name) {
        sel.project = null; sel.name = null;
        $("detail-view").classList.add("hidden");
        $("detail-empty").classList.remove("hidden");
      }
    };
    box.appendChild(item);
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
}

/* ---------- 步骤时间轴：三肤共存（地铁 metro / 甘特 gantt / 卡片树 cards） ---------- */

/* 共享：拖拽 + 滚轮横向滑动 */
const PHASE_LABELS = {
  understand: "理解和求证问题",
  plan: "生成执行计划",
  execute: "执行",
  review: "审核结果",
  evolution: "进化",
};
function phaseLabel(name) {
  return PHASE_LABELS[name] || name;
}

/* fermate（plan-only）：plan 之后阶段不存在，时间轴只展示前两阶段 */
function visibleNodes(nodes, info) {
  if (!info.force_fermate) return nodes;
  return nodes.filter((n) => n.phase === "understand" || n.phase === "plan");
}

function attachTimelineScroll(box) {
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
}

function tlEmpty(box) {
  box.innerHTML = `<div class="tl-empty">无步骤数据</div>`;
  $("tl-summary").textContent = "";
}

/* 树形 DOM（metro 与 cards 共用；视觉差异全部由容器类 CSS 决定）：
   major_state 分带 -> minor_state 为枝 -> step 为叶（嵌迷你耗时条）。 */
const ART_NODE = { "understand:4": "understands", "plan:4": "plans" };
const ART_LABEL = { understands: "understand.md", plans: "plan.md" };

function artLink(kind) {
  const q = `project=${encodeURIComponent(sel.project)}` +
    `&name=${encodeURIComponent(sel.name)}&kind=${kind}`;
  return `<a class="art-link" target="_blank" href="/static/artifact.html?${q}">${ART_LABEL[kind]}</a>`;
}

function renderTimelineTree(stats, nodes, info, artifacts) {
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
  for (const n of visibleNodes(nodes, info)) {
    let ph = phases.find((p) => p.name === n.phase);
    if (!ph) { ph = { name: n.phase, nodes: [] }; phases.push(ph); }
    ph.nodes.push(n);
  }
  if (!phases.length) { tlEmpty(box); return; }
  const track = document.createElement("div");
  track.className = "tl-track";
  for (const ph of phases) {
    const doneCount = ph.nodes.filter((n) => n.status === "done").length;
    const phStatus = ph.nodes.every((n) => n.status === "done")
      ? "done"
      : ph.nodes.some((n) => n.status === "current") ? "current" : "pending";
    // major_state 汇总：跨节点聚合该阶段全部 step
    const pstat = { dur: 0, turns: 0, tin: 0, tout: 0, cost: 0 };
    for (const n of ph.nodes) {
      for (let i = 1; i <= n.sub_total; i++) {
        const a = stepMap.get(`${n.node_id}#${i}`);
        if (a) {
          pstat.dur += a.dur; pstat.turns += a.turns;
          pstat.tin += a.tin; pstat.tout += a.tout; pstat.cost += a.cost;
        }
      }
    }
    const phEl = document.createElement("div");
    phEl.className = `tl-phase ${phStatus}`;
    phEl.innerHTML =
      `<div class="tl-phase-head">${esc(phaseLabel(ph.name))}` +
      `<span class="num">${doneCount}/${ph.nodes.length}</span></div>` +
      (pstat.turns > 0
        ? `<div class="tl-pstat num">Σ ${pstat.dur}s · ${pstat.turns}轮 · ` +
          `in${fmtTok(pstat.tin)}/out${fmtTok(pstat.tout)} · $${pstat.cost.toFixed(2)}</div>`
        : "");
    const branches = document.createElement("div");
    branches.className = "tl-branches";
    for (const n of ph.nodes) {
      let nodeMax = 1;
      const nstat = { dur: 0, turns: 0, tin: 0, tout: 0, cost: 0 };
      for (let i = 1; i <= n.sub_total; i++) {
        const a = stepMap.get(`${n.node_id}#${i}`);
        if (a) {
          if (a.dur > nodeMax) nodeMax = a.dur;
          nstat.dur += a.dur; nstat.turns += a.turns;
          nstat.tin += a.tin; nstat.tout += a.tout; nstat.cost += a.cost;
        }
      }
      const nodeEl = document.createElement("div");
      nodeEl.className = `tl-node ${n.status}`;
      const head = document.createElement("div");
      head.className = "tl-node-head";
      head.textContent = n.label;
      nodeEl.appendChild(head);
      if (nstat.turns > 0) {
        const st = document.createElement("div");
        st.className = "tl-nstat num";
        st.textContent =
          `Σ ${nstat.dur}s · ${nstat.turns}轮 · ` +
          `in${fmtTok(nstat.tin)}/out${fmtTok(nstat.tout)} · $${nstat.cost.toFixed(2)}`;
        nodeEl.appendChild(st);
      }
      // 归属节点的产物链接（新页面阅读）
      const artKind = ART_NODE[n.node_id];
      if (artKind && artifacts && artifacts[artKind] && artifacts[artKind].exists) {
        const al = document.createElement("div");
        al.className = "tl-art";
        al.innerHTML = artLink(artKind);
        nodeEl.appendChild(al);
      }
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
            `${n.label} #${i}\n耗时 ${a.dur}s · ${a.turns} 轮\n` +
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
  attachTimelineScroll(box);
  const totTurns = [...stepMap.values()].reduce((a, r) => a + r.turns, 0);
  const totDur = [...stepMap.values()].reduce((a, r) => a + r.dur, 0);
  const totCost = [...stepMap.values()].reduce((a, r) => a + r.cost, 0);
  $("tl-summary").textContent =
    `${stepMap.size} 步已执行 · ${totTurns} 轮 · ${totDur}s · $${totCost.toFixed(2)}`;
}

/* 甘特泳道：节点为道、段为真实时间定位的横条。 */
function renderTimelineGantt(stats, nodes, info, artifacts) {
  const box = $("timeline");
  box.innerHTML = "";
  const segs = stats.filter((s) => s.ts);
  if (!segs.length) { tlEmpty(box); return; }
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

  const byNode = new Map();
  for (const s of segs) {
    if (!byNode.has(s.node)) byNode.set(s.node, []);
    byNode.get(s.node).push(s);
  }
  let lastPhase = null, group = null;
  for (const n of visibleNodes(nodes, info)) {
    const nodeSegs = byNode.get(n.node_id);
    if (!nodeSegs) continue;
    if (n.phase !== lastPhase) {
      lastPhase = n.phase;
      group = document.createElement("div");
      group.className = "gt-group";
      const ph = document.createElement("div");
      ph.className = "gt-phase";
      ph.textContent = phaseLabel(n.phase);
      // major_state 汇总（本阶段已跑段的合计）
      const pstat = { dur: 0, turns: 0, tin: 0, tout: 0, cost: 0 };
      for (const nn of visibleNodes(nodes, info)) {
        if (nn.phase !== n.phase) continue;
        for (const s of byNode.get(nn.node_id) || []) {
          pstat.dur += s.duration_s || 0;
          pstat.turns += s.num_turns || 0;
          pstat.tin += s.input_tokens || 0;
          pstat.tout += s.output_tokens || 0;
          pstat.cost += s.cost_usd || 0;
        }
      }
      if (pstat.turns > 0) {
        const st = document.createElement("span");
        st.className = "gt-pstat num";
        st.textContent =
          `Σ ${pstat.dur}s · ${pstat.turns}轮 · ` +
          `in${fmtTok(pstat.tin)}/out${fmtTok(pstat.tout)} · $${pstat.cost.toFixed(2)}`;
        ph.appendChild(st);
      }
      group.appendChild(ph);
      root.appendChild(group);
    }
    const lane = document.createElement("div");
    lane.className = "gt-lane" + (n.status === "current" ? " cur" : "");
    const label = document.createElement("div");
    label.className = "gt-label";
    label.textContent = n.label;
    const nstat = { dur: 0, turns: 0, tin: 0, tout: 0 };
    for (const s of nodeSegs) {
      nstat.dur += s.duration_s || 0;
      nstat.turns += s.num_turns || 0;
      nstat.tin += s.input_tokens || 0;
      nstat.tout += s.output_tokens || 0;
    }
    if (nstat.turns > 0) {
      const st = document.createElement("div");
      st.className = "gt-lstat num";
      st.textContent =
        `Σ ${nstat.dur}s · ${nstat.turns}轮 · in${fmtTok(nstat.tin)}/out${fmtTok(nstat.tout)}`;
      label.appendChild(st);
    }
    const artKind = ART_NODE[n.node_id];
    if (artKind && artifacts && artifacts[artKind] && artifacts[artKind].exists) {
      const al = document.createElement("div");
      al.className = "tl-art";
      al.innerHTML = artLink(artKind);
      label.appendChild(al);
    }
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
        bar.title = `${n.label} #${s.sub_step}\n${s.ts} · 无统计数据`;
      } else {
        bar.className = "gt-bar" + (isCur ? " cur" : "");
        bar.style.left = x + "px";
        bar.style.width = Math.max(3, Math.round(s.duration_s * scale)) + "px";
        bar.title =
          `${n.label} #${s.sub_step}\n${s.ts} 起 · 耗时 ${s.duration_s}s · ` +
          `${fmtDur(s.num_turns)} 轮\ntok in ${s.input_tokens ?? "-"} / out ` +
          `${s.output_tokens ?? "-"}\n$${(s.cost_usd ?? 0).toFixed(3)}`;
        if (s.duration_s * scale > 68) {
          bar.textContent = `#${s.sub_step} ${s.duration_s}s·${fmtDur(s.num_turns)}轮`;
        }
      }
      rail.appendChild(bar);
    }
    lane.appendChild(rail);
    group.appendChild(lane);
  }

  const nowLine = document.createElement("div");
  nowLine.className = "gt-now";
  nowLine.style.left = LABEL_W + Math.round(((now - t0) / 1000) * scale) + "px";
  nowLine.title = "现在";
  root.appendChild(nowLine);

  box.appendChild(root);
  attachTimelineScroll(box);
  const totTurns = segs.reduce((a, s) => a + (s.num_turns || 0), 0);
  const totDur = segs.reduce((a, s) => a + (s.duration_s || 0), 0);
  const totCost = segs.reduce((a, s) => a + (s.cost_usd || 0), 0);
  $("tl-summary").textContent =
    `${segs.length} 段 · ${totTurns} 轮 · ${totDur}s · $${totCost.toFixed(2)}`;
}

/* 换肤分发：localStorage 记忆（dl_tl_skin），默认卡片树 */
const TL_SKINS = new Set(["metro", "gantt", "cards"]);
function tlSkin() {
  const s = localStorage.getItem("dl_tl_skin");
  return TL_SKINS.has(s) ? s : "cards";
}

function renderTimeline(stats, nodes, info, artifacts) {
  const box = $("timeline");
  const skin = tlSkin();
  box.classList.remove("metro", "gantt", "cards");
  box.classList.add(skin);
  // 总进度条：已完成 step / 可见 step（fermate 只计前两阶段）
  const vis = visibleNodes(nodes, info);
  const total = vis.reduce((a, n) => a + n.sub_total, 0);
  const visIds = new Set(vis.map((n) => n.node_id));
  const doneKeys = new Set(
    stats.filter((s) => visIds.has(s.node)).map((s) => `${s.node}#${s.sub_step}`));
  const prog = $("tl-progress");
  if (total > 0 && doneKeys.size > 0) {
    const pct = Math.round((doneKeys.size / total) * 100);
    $("tl-prog-fill").style.width = pct + "%";
    $("tl-prog-label").textContent = `${doneKeys.size}/${total} 步 · ${pct}%`;
    prog.classList.remove("hidden");
  } else {
    prog.classList.add("hidden");
  }
  if (skin === "gantt") renderTimelineGantt(stats, nodes, info, artifacts);
  else renderTimelineTree(stats, nodes, info, artifacts);
  document.querySelectorAll("#tl-switch button").forEach((b) =>
    b.classList.toggle("on", b.dataset.skin === skin));
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
  if (d.driver_pid) {
    box.appendChild(mkBtn("暂停", async () => {
      const r = await post("/api/pause", { project: proj, name });
      alert(r.msg); refreshDetail();
    }));
  } else {
    box.appendChild(mkBtn("恢复驱动", async () => {
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

/* 改动面 + 证据链加载（选中工作流时加载一次，「刷新产物」手动重载，不拖 SSE）。
   改动面 = plan 的 change_point 审核卡片：改前/改后 + worktree 实读现状上下文。 */
async function loadOutputs() {
  if (!sel.project) return;
  const cpBox = $("change-points");
  const evBox = $("outputs");
  cpBox.innerHTML = `<div class="tl-empty">加载中…</div>`;
  evBox.innerHTML = "";
  const qs = `project=${encodeURIComponent(sel.project)}&name=${encodeURIComponent(sel.name)}`;
  const r = await fetch(`/api/outputs?${qs}`);
  const d = await r.json();

  // 代码改动面
  cpBox.innerHTML = "";
  $("cp-count").textContent = d.change_points.length
    ? `${d.change_points.length} 处改动（来自 plan.md，现状为 worktree 实读）` : "";
  if (d.change_points.length) {
    for (const c of d.change_points) {
      const card = document.createElement("div");
      card.className = "cp-card";
      let html =
        `<div class="cp-head"><span class="cp-file num">${esc(c.file)}</span>` +
        (c.method !== "-" ? ` <span class="num">${esc(c.method)}</span>` : "") +
        ` <span class="num">L${esc(c.line)}</span>` +
        `<span class="tag warn">${esc(c.action)}</span></div>`;
      if (c.before || c.after) {
        html += `<div class="cp-diff">` +
          (c.before
            ? `<div class="cp-before"><span class="cp-sign">-</span><span>${esc(c.before)}</span></div>`
            : "") +
          (c.after
            ? `<div class="cp-after"><span class="cp-sign">+</span><span>${esc(c.after)}</span></div>`
            : "") +
          `</div>`;
      }
      if (c.context) {
        html += `<div class="cp-ctx">` +
          c.context.lines.map((t, i) => {
            const n = c.context.start + i;
            const isA = n === c.context.anchor;
            return `<div class="cp-line${isA ? " anchor" : ""}">` +
              `<span class="cp-ln num">${isA ? "▶" : ""}${n}</span>` +
              `<span>${esc(t)}</span></div>`;
          }).join("") +
          `</div>`;
      }
      card.innerHTML = html;
      cpBox.appendChild(card);
    }
  } else {
    cpBox.innerHTML =
      `<div class="tl-empty">plan 尚未产出 change_point（到达 plan 阶段后自动出现）</div>`;
  }

  // 证据链
  if (d.evidence.length) {
    let lastStage = null;
    for (const e of d.evidence) {
      const stage = [e.major_stage, e.minor_stage].filter(Boolean).join(" / ") || e.kind;
      if (stage !== lastStage) {
        lastStage = stage;
        const sh = document.createElement("div");
        sh.className = "ev-stage";
        sh.textContent = stage;
        evBox.appendChild(sh);
      }
      const item = document.createElement("div");
      item.className = "ev-item";
      const qa = (e.q.length || e.a.length)
        ? `<details class="ev-qa"><summary class="num">问答 ${e.q.length}q/${e.a.length}a</summary>` +
          e.q.map((q, i) =>
            `<p class="ev-q">Q${i + 1} ${esc(q)}</p>` +
            (e.a[i] ? `<p class="ev-a">A ${esc(e.a[i])}</p>` : "")).join("") +
          `</details>`
        : "";
      item.innerHTML =
        `<div class="ev-head"><span class="num">#${e.sub_step ?? "-"}</span> ` +
        `<span class="ev-skill">${esc(e.skill || e.kind)}</span> ${esc(e.purpose)}</div>` +
        (e.conclusion ? `<div class="ev-concl">${esc(e.conclusion)}</div>` : "") + qa;
      evBox.appendChild(item);
    }
  } else {
    evBox.innerHTML = `<div class="tl-empty">暂无证据链记录</div>`;
  }
}

async function refreshDetail() {
  if (!sel.project) return;
  const r = await fetch(
    `/api/workflow?project=${encodeURIComponent(sel.project)}` +
    `&name=${encodeURIComponent(sel.name)}`);
  const d = await r.json();
  const modeTags = (d.info.force_tacet ? `<span class="tag mode-tacet">tacet</span>` : "") +
    (d.info.force_fermate ? `<span class="tag mode-fermate">fermate</span>` : "");
  $("d-title").innerHTML = `${esc(d.info.name)} · ${esc(d.info.node)}` +
    (d.driver_pid ? `（driver #${d.driver_pid}）` : "（driver 已停）") + modeTags;
  // 在跑徽标：当前步已跑时长（从末段记录起算，SSE 2s 刷新）
  const live = $("tl-live");
  if (d.driver_pid && d.stats.length) {
    const lastTs = Math.max(...d.stats.map((x) => new Date(x.ts).getTime()));
    const elapsed = Math.max(0, Math.round((Date.now() - lastTs) / 1000));
    live.innerHTML =
      `<span class="live-badge"><span class="dot ok"></span>在跑 · 当前步 ${elapsed}s</span>`;
  } else if (d.driver_pid) {
    live.innerHTML = `<span class="live-badge"><span class="dot ok"></span>在跑</span>`;
  } else {
    live.textContent = "";
  }
  $("d-statement").textContent = d.info.problem_statement;
  renderTimeline(d.stats, d.info.nodes, d.info, d.artifacts);
  renderInteract(d);
  $("log-tail").textContent = d.log_tail;
}

$("sidebar-toggle").onclick = () => {
  const sb = $("sidebar");
  const collapsed = sb.classList.toggle("collapsed");
  $("sidebar-toggle").textContent = collapsed ? "展开" : "收起";
};
// 手机端默认收起侧栏（窄屏交互让位详情区）
if (window.matchMedia("(max-width: 768px)").matches) {
  $("sidebar").classList.add("collapsed");
  $("sidebar-toggle").textContent = "展开";
}

$("outputs-refresh").onclick = () => loadOutputs();

/* 新建工作流弹窗：项目下拉（config 登记源）+ 模式选择（fermate/forte/tacet） */
let lastProjects = [];
let lastWorkflowNames = new Set();  // 已存在工作流名（生成名防碰撞用）

/* 从 problem_statement 提取英文词自动生成名称（≤3 词，_ 连接）：
   提取拉丁 token -> 小写 -> 去停用词 -> 取前 3；纯中文陈述提取不出词则留空手填。
   名称正则约束 ^[a-z0-9][a-z0-9_-]{0,63}$（与后端 _NAME_RE 一致）。 */
const NAME_STOP = new Set([
  "the", "a", "an", "of", "for", "and", "or", "is", "are", "to", "in", "on",
  "we", "our", "you", "your", "this", "that", "it", "its", "be", "by", "at",
  "as", "if", "so", "no", "not", "do", "does", "did", "has", "have", "had",
]);
function genName(statement) {
  const words = (statement.match(/[a-zA-Z][a-zA-Z0-9]*/g) || [])
    .map((w) => w.toLowerCase())
    .filter((w) => !NAME_STOP.has(w) && w.length > 1);
  const uniq = [...new Set(words)].slice(0, 3);
  return uniq.join("_").slice(0, 63);
}
$("cf-statement").addEventListener("input", () => {
  $("cf-name").value = genName($("cf-statement").value);
});

/* 提交时定名：生成 -> 空则拦（纯中文陈述）-> 防碰撞加 _2/_3 后缀 */
function dedupeName(base) {
  if (!lastWorkflowNames.has(base)) return base;
  for (let i = 2; ; i++) {
    const cand = `${base}_${i}`;
    if (!lastWorkflowNames.has(cand)) return cand;
  }
}

function openCreateModal() {
  const selP = $("cf-project");
  selP.innerHTML = lastProjects.map((p) =>
    `<option value="${esc(p)}">${esc(p)}</option>`).join("");
  $("create-modal").classList.remove("hidden");
  $("cf-statement").focus();
}
function closeCreateModal() {
  $("create-modal").classList.add("hidden");
}
$("create-toggle").onclick = openCreateModal;
$("create-close").onclick = closeCreateModal;
$("create-modal").onclick = (e) => {
  if (e.target === $("create-modal")) closeCreateModal();
};
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeCreateModal();
});

/* 模式卡：每行内单选（范围 / 轨道两个维度，行内互斥、跨行自由组合） */
document.querySelectorAll(".mode-cards").forEach((row) => {
  row.querySelectorAll(".mode-card").forEach((c) => {
    c.onclick = () => {
      row.querySelectorAll(".mode-card").forEach((x) => x.classList.remove("sel"));
      c.classList.add("sel");
    };
  });
});

$("create-form").onsubmit = async (e) => {
  e.preventDefault();
  const statement = $("cf-statement").value.trim();
  const base = genName(statement);
  if (!base) {
    alert("问题里没有可识别的英文词，无法生成工作流名——请在问题中包含英文关键词（如因子名/页面名）");
    return;
  }
  const name = dedupeName(base);
  const scope = document.querySelector("#scope-cards .mode-card.sel").dataset.v;
  const tacet = document.querySelector("#track-cards .mode-card.sel").dataset.v === "tacet";
  const r = await post("/api/create", {
    project: $("cf-project").value,
    name,
    statement,
    scope,
    tacet,
  });
  alert(r.ok ? `已创建 ${name}` : r.msg);
  if (r.ok) closeCreateModal();
};

document.querySelectorAll("#tl-switch button").forEach((b) => {
  b.onclick = () => {
    localStorage.setItem("dl_tl_skin", b.dataset.skin);
    refreshDetail();
  };
});

const es = new EventSource("/api/events");
es.onmessage = (e) => {
  const data = JSON.parse(e.data);
  lastProjects = data.projects || [];
  lastWorkflowNames = new Set(data.workflows.map((w) => w.name));
  renderSidebar(data.workflows);
  if (sel.project) refreshDetail();
};
