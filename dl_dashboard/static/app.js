/* dl-workflow 控制台：SSE 驱动，左侧工作流栏 + 右侧详情（步骤时间轴）。 */
"use strict";

const sel = { project: null, name: null };
const $ = (id) => document.getElementById(id);

/* 答题排队（2026-09-17，B 方案）：问题已 stash 但注入段台账未落（「准备中」
   窗口，qoder 冷段 30-90s×5 交互步）时允许先作答——答案本地暂存，
   inject_ready 翻面后自动走既有守卫 POST（服务端时序铁律不动）。等待与
   答题并行，窗口期感知延迟归零。问题集重 stash（ts 变）作废暂存——
   防答案注进已换的题目。 */
let parked = null;  // {project, name, ts, answer, inflight, retries}
const PARKED_KEY = "dl-parked-answer";
function setParked(v) {
  // localStorage 持久化——旧版纯内存，刷新页面静默丢暂存（用户以为排着队，
  // 实际没了 = silent failure）。inflight/retries 是运行态不落盘。
  parked = v;
  try {
    if (v) localStorage.setItem(PARKED_KEY, JSON.stringify(
      { project: v.project, name: v.name, ts: v.ts, answer: v.answer,
        retries: v.retries || 0 }));
    else localStorage.removeItem(PARKED_KEY);
  } catch (e) { /* 隐私模式等写失败：退化为内存态 */ }
}
try {
  const raw = localStorage.getItem(PARKED_KEY);
  if (raw) {
    const v = JSON.parse(raw);
    if (v && v.project && v.name && v.ts && typeof v.answer === "string") {
      parked = { ...v, inflight: false };  // 刷新恢复：未在飞，等生命周期判
    }
  }
} catch (e) { /* 坏数据即丢弃 */ }

async function post(url, body) {
  // fail-safe：代理/隧道可能在长操作时截断响应（inject 模型轮 1-3min 实爆：
  // 公网地址 ~180s 超时，服务端照常跑完，前端静默复活按钮零反馈）——
  // 失败必须如实告知「状态未知」，绝不静默。
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return await r.json();
  } catch (e) {
    return { ok: false,
             msg: "请求未正常返回（网络/代理中断）——操作可能已在服务端执行，" +
                  "状态稍候自动刷新，勿急于重复操作" };
  }
}

// 问题描述折叠/展开（stmt-collapse）：CSS line-clamp 截断，溢出才显示按钮
function _stmt_collapse_sync(el) {
  el.classList.add("stmt-collapsed");
  let btn = el.nextElementSibling;
  if (!btn || !btn.classList || !btn.classList.contains("stmt-toggle")) {
    btn = document.createElement("button");
    btn.type = "button";
    btn.className = "stmt-toggle";
    el.parentNode.insertBefore(btn, el.nextSibling);
  }
  // class 先加再量：scrollHeight（全文高）> clientHeight（截断高）= 真溢出
  const overflow = el.scrollHeight > el.clientHeight + 1;
  btn.classList.toggle("hidden", !overflow);
  btn.textContent = "展开全部 ▾";
  btn.onclick = () => {
    const collapsed = el.classList.toggle("stmt-collapsed");
    btn.textContent = collapsed ? "展开全部 ▾" : "收起 ▴";
  };
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

/* 总耗时人性化：35m07s / 1h05m（在跑徽标的工作流总执行时间用） */
/* 步骤起止时间（用户裁决 2026-09-18：时间轴除耗时外展示开始/结束）。
   ts 形如 "2026-09-18T12:56:30"（本地时间）；行内紧凑 HH:MM:SS，
   tooltip 带完整日期。 */
function fmtClock(ts) {
  return (ts && ts.split("T")[1]) || ts || "";
}
function fmtClockD(d) {
  return d ? d.toTimeString().slice(0, 8) : "";
}
function stepTimes(stepSegs) {
  // 步级起止聚合：开始=本步最早段 ts；结束=已完成段 ts+duration_s 的最大者
  const starts = stepSegs.map((s) => s.ts).filter(Boolean).sort();
  let end = null;
  for (const s of stepSegs) {
    if (s.duration_s == null || !s.ts) continue;  // 在飞行无结束
    const e = new Date(new Date(s.ts).getTime() + s.duration_s * 1000);
    if (!end || e > end) end = e;
  }
  return { start: starts[0] || null, end };
}

function fmtHMS(s) {
  s = Math.max(0, Math.round(s));
  if (s >= 3600) {
    return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  }
  return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
}

/* 子步中文名（scanner step_labels 单源，如 逼问定义）；缺定义回退 #n */
function stepName(n, i) {
  return (n.step_labels && n.step_labels[i]) || `#${i}`;
}

function isWaiting(w) {
  // gate_actionable（scanner 单源）= 门栏扣留 / 闸门后置阶段 pending——
  // 替代旧「held && pending」近似（漏阶段闸门等待态）
  return w.need_user || w.gate_actionable;
}

/* 自定义确认弹窗（替代原生 confirm）：返回 Promise<boolean>。
   取消路径：× / 取消按钮 / 点遮罩 / Esc；danger=true 时确认键红色。 */
function showConfirm({ title, body, okText = "确认", danger = false }) {
  return new Promise((resolve) => {
    const veil = document.createElement("div");
    veil.className = "modal-veil";
    veil.innerHTML =
      `<div class="modal confirm-modal" role="dialog" aria-modal="true">` +
      `<div class="modal-head"><h3>${esc(title)}</h3>` +
      `<button type="button" class="modal-close" data-x>×</button></div>` +
      `<div class="confirm-body">${esc(body)}</div>` +
      `<div class="modal-actions">` +
      `<button type="button" class="btn" data-no>取消</button>` +
      `<button type="button" class="btn ${danger ? "danger" : "primary"}" data-ok>${esc(okText)}</button>` +
      `</div></div>`;
    const close = (v) => { veil.remove(); resolve(v); };
    veil.querySelector("[data-x]").onclick = () => close(false);
    veil.querySelector("[data-no]").onclick = () => close(false);
    veil.querySelector("[data-ok]").onclick = () => close(true);
    veil.onclick = (e) => { if (e.target === veil) close(false); };
    document.addEventListener("keydown", function onEsc(e) {
      if (e.key === "Escape") {
        document.removeEventListener("keydown", onEsc);
        close(false);
      }
    });
    document.body.appendChild(veil);
  });
}

/* toast 通知条（替代原生 alert）：右上角浮层，成功绿/失败红，
   3.5s 自动消隐，点击立即关闭；长消息内部滚动。 */
function toast(msg, ok = true) {
  const box = $("toast-box");
  const t = document.createElement("div");
  t.className = "toast" + (ok ? "" : " err");
  t.textContent = msg;
  const kill = () => t.remove();
  t.onclick = kill;
  box.appendChild(t);
  setTimeout(kill, ok ? 3500 : 8000);  // 失败 toast 留 8s——错误必须被看见
}

function selectWorkflow(project, name) {
  sel.project = project; sel.name = name;
  lastDetailFp = "";  // 换工作流：详情强制全量渲
  // 高亮即时翻转（侧栏不整列重建）
  document.querySelectorAll(".wf-item.sel").forEach((x) => x.classList.remove("sel"));
  document.querySelector(
    `.wf-item[data-project="${CSS.escape(project)}"][data-name="${CSS.escape(name)}"]`)
    ?.classList.add("sel");
  $("detail-empty").classList.add("hidden");
  $("detail-view").classList.remove("hidden");
  // 手机端选中后自动收起侧栏，让位详情区
  if (window.matchMedia("(max-width: 768px)").matches) {
    $("sidebar").classList.add("collapsed");
    $("sidebar-toggle").textContent = "展开";
  }
  refreshDetail();
  loadOutputs();
}

function renderSidebar(workflows) {
  const box = $("wf-list");
  box.innerHTML = "";
  for (const w of workflows) {
    const item = document.createElement("div");
    item.className = "wf-item";
    item.dataset.project = w.project;
    item.dataset.name = w.name;
    if (w.error) item.classList.add("err");
    if (sel.project === w.project && sel.name === w.name) item.classList.add("sel");
    const dot = w.error ? "err" : isWaiting(w) ? "wait" : w.driver_pid ? "ok" : "off";
    const modeTag = (w.force_tacet ? `<span class="tag mode-tacet">tacet</span>` : "") +
      (w.force_fermate ? `<span class="tag mode-fermate">fermate</span>` : "") +
      (w.gate === "done" ? `<span class="tag mode-done">已完结</span>` : "") +
      (w.engine && w.engine !== "claude"
        // 非默认引擎才显徽标（claude=默认不吵；scanner 旧实例兜底 claude 不会到这）
        ? `<span class="engine-badge engine-${esc(w.engine)}">${w.engine === "qodercli" ? "qoder" : esc(w.engine)}</span>` : "");
    item.innerHTML =
      `<div class="wf-line1"><span class="dot ${dot}"></span>` +
      `<span class="wf-name">${esc(w.name)}</span>${modeTag}` +
      `<button class="wf-del" title="删除工作流">×</button></div>` +
      `<div class="wf-line2"><span class="num">${w.error ? "状态不可读" : esc(w.node)}</span>` +
      `<span class="num">$${esc(w.totals.cost_usd)}</span></div>`;
    item.onclick = () => selectWorkflow(w.project, w.name);
    item.querySelector(".wf-del").onclick = async (e) => {
      e.stopPropagation();
      const yes = await showConfirm({
        title: `删除工作流 ${w.name}`,
        body: "将彻底删除 worktree + 分支 + 元数据 + 产物文档（改动面/understand/证据链），不可恢复。",
        okText: "删除",
        danger: true,
      });
      if (!yes) return;
      const r = await post("/api/delete", { project: w.project, name: w.name });
      toast(r.msg, r.ok);
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

/* fermate（plan-only）可见集由后端 scanner 单源过滤下发（dl_flow_nodes
   fermate_cut_node / fermate_phase_reachable）——前端不再手写过滤，
   防展示层掉队于脊柱演进（32/43=74% 幽灵进度事故）。 */

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
const ART_PHASE = { understands: "understand", plans: "plan", proposals: "plan" };
// 产物区只展示技术方案（用户 2026-09-11 裁决：understand.html/plan.html 不上 UI，
// 后端照产不删）；proposals 显示名=技术方案.html（系统内部文件名 proposal.html 不动）
const ART_LABEL = {
  proposals: { html: "技术方案.html", md: "技术方案.md" },
};
const ART_KINDS_VISIBLE = ["proposals"];

/* 产物链接挂载点 = 对应阶段最后一个可见节点（fermate 下 plan:4 不存在、
   tacet 下 understand:4 静默——静态映射会丢链接，动态选存活节点） */
function artAnchorNode(nodes, kind) {
  const cands = nodes.filter((n) => n.phase === ART_PHASE[kind] && n.steps.length > 0);
  return cands.length ? cands[cands.length - 1].node_id : null;
}

/* 产物链接：html 存在（v0.3.0 伴随导出）→ /artifact-html 人读渲染版；
   不存在 → 旧 md 查看页兜底。所见格式即所标（标签 .html/.md 不隐式兜底）。 */
function artLink(kind, artifacts) {
  const q = `project=${encodeURIComponent(sel.project)}` +
    `&name=${encodeURIComponent(sel.name)}&kind=${kind}`;
  if (artifacts && artifacts[kind] && artifacts[kind].html_exists) {
    return `<a class="art-link" target="_blank" href="/artifact-html?${q}">${ART_LABEL[kind].html}</a>`;
  }
  return `<a class="art-link" target="_blank" href="/static/artifact.html?${q}">${ART_LABEL[kind].md}</a>`;
}

function renderTimelineTree(stats, nodes, info, artifacts, driverPid) {
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
      for (const i of n.steps) {
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
    // 整节点静默（tacet 非脊柱/fermate 裁剪节点，无可见步）不展示
    const showNodes = ph.nodes.filter((n) => n.steps.length > 0 || n.status === "current");
    if (!showNodes.length) continue;
    const branches = document.createElement("div");
    branches.className = "tl-branches";
    for (const n of showNodes) {
      let nodeMax = 1;
      const nstat = { dur: 0, turns: 0, tin: 0, tout: 0, cost: 0 };
      for (const i of n.steps) {
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
      for (const kind of ART_KINDS_VISIBLE) {
        if (artAnchorNode(nodes, kind) === n.node_id &&
            artifacts && artifacts[kind] && artifacts[kind].exists) {
          const al = document.createElement("div");
          al.className = "tl-art";
          al.innerHTML = artLink(kind, artifacts);
          nodeEl.appendChild(al);
        }
      }
      const leaves = document.createElement("div");
      leaves.className = "tl-leaves";
      for (const i of n.steps) {
        const key = `${n.node_id}#${i}`;
        const a = stepMap.get(key);
        const isCur = n.status === "current" && i === info.sub_step_index;
        const leaf = document.createElement("div");
        leaf.className = "tl-leaf" + (a ? " done" : isCur ? " cur" : " todo");
        if (isCur && !a && !driverPid) {
          // driver 停（暂停/等答/门栏/死）当前步不计时——旧版无条件按
          // current_segment/末段 ts 起算，暂停后计时永远涨（2026-09-17 实爆）；
          // 与在跑徽标同规（徽标早已 driver_pid 门控，driver 停不显示）
          leaf.innerHTML =
            `<div class="tl-l1"><span class="tl-lid">${esc(stepName(n, i))}</span>` +
            `<span class="tl-ldur">未在跑</span></div>`;
        } else if (isCur && !a) {
          // 在跑步：实时计时——在飞段起点（current_segment，driver 起跑落盘，
          // 不含段间空隙）+ 本步已完成段耗时累加（交互步 prep/问答/注入多段
          // 串行，旧版只算在飞段——答题触发新段后显示归零「重新计算」，
          // 2026-09-17 实爆）。duration_s==null 的在飞行不入累加（防双计）。
          const cs = info.current_segment;
          const csHit = cs && cs.node === n.node_id &&
            Number(cs.sub_step) === i && cs.started_at;
          const stepSegs = stats.filter((x) => x.node === n.node_id && x.sub_step === i);
          const priorDur = stepSegs.reduce((acc, s) => acc + (s.duration_s || 0), 0);
          const lastSeg = stepSegs[stepSegs.length - 1];
          const elapsed = csHit
            ? priorDur + Math.max(0, Math.round((Date.now() - new Date(cs.started_at).getTime()) / 1000))
            : lastSeg
              // 回退（在飞段无 current_segment，如旧 driver）：末段在飞才从
              // 其 ts 起算；末段已完成则耗时已在 priorDur，只加 0（防双计）
              ? priorDur + (lastSeg.duration_s == null
                  ? Math.max(0, Math.round((Date.now() - new Date(lastSeg.ts).getTime()) / 1000))
                  : 0)
              : null;
          leaf.innerHTML =
            `<div class="tl-l1"><span class="tl-lid">${esc(stepName(n, i))}</span>` +
            `<span class="tl-ldur">在跑${elapsed != null ? ` ${elapsed}s` : ""}</span></div>`;
        } else if (a) {
          const barW = Math.max(2, Math.round((a.dur / nodeMax) * 90));
          const tt = stepTimes(stats.filter(
            (x) => x.node === n.node_id && x.sub_step === i));
          leaf.title =
            `${n.label} ${stepName(n, i)}\n开始 ${tt.start || "?"}\n` +
            `结束 ${tt.end ? tt.end.toLocaleString() : "?"}\n` +
            `耗时 ${a.dur}s · ${a.turns} 轮\n` +
            `tok in ${a.tin} / out ${a.tout}\n$${a.cost.toFixed(3)}`;
          leaf.innerHTML =
            `<div class="tl-l1"><span class="tl-lid">${esc(stepName(n, i))}</span>` +
            `<span class="tl-bar" style="width:${barW}px"></span>` +
            `<span class="tl-ldur num">${a.dur}s</span></div>` +
            `<div class="tl-l2 num">` +
            (tt.start
              ? `${fmtClock(tt.start)}–${tt.end ? fmtClockD(tt.end) : "…"} · `
              : "") +
            `${a.turns}轮 ` +
            `in${fmtTok(a.tin)}/out${fmtTok(a.tout)} ` +
            `$${a.cost.toFixed(2)}</div>`;
        } else {
          leaf.innerHTML = `<div class="tl-l1"><span class="tl-lid">${esc(stepName(n, i))}</span></div>`;
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
function renderTimelineGantt(stats, nodes, info, artifacts, driverPid) {
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
  for (const n of nodes) {
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
      for (const nn of nodes) {
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
    for (const kind of ART_KINDS_VISIBLE) {
      if (artAnchorNode(nodes, kind) === n.node_id &&
          artifacts && artifacts[kind] && artifacts[kind].exists) {
        const al = document.createElement("div");
        al.className = "tl-art";
        al.innerHTML = artLink(kind, artifacts);
        label.appendChild(al);
      }
    }
    lane.appendChild(label);
    const rail = document.createElement("div");
    rail.className = "gt-rail";
    for (const s of nodeSegs) {
      const x = Math.round(((new Date(s.ts).getTime() - t0) / 1000) * scale);
      const isCur = n.status === "current";
      const bar = document.createElement("div");
      if (s.duration_s == null && isCur && driverPid) {
        // 在跑段：sky 实时条，右缘=now（每 SSE 拍增长）——起点优先在飞段
        // current_segment.started_at（不含段间空隙），缺它回退末行 ts
        const cs = info.current_segment;
        const startTs = (cs && cs.node === n.node_id && cs.started_at)
          ? cs.started_at
          : s.ts;
        const elapsed = Math.max(1, Math.round((now - new Date(startTs).getTime()) / 1000));
        bar.className = "gt-bar cur running";
        bar.style.left = x + "px";
        bar.style.width = Math.max(3, Math.round(elapsed * scale)) + "px";
        bar.title = `${n.label} ${stepName(n, s.sub_step)}\n${s.ts} 起 · 在跑 ${elapsed}s`;
        if (elapsed * scale > 68) {
          bar.textContent = `${stepName(n, s.sub_step)} 在跑 ${elapsed}s`;
        }
      } else if (s.duration_s == null) {
        bar.className = "gt-mark";
        bar.style.left = x + "px";
        bar.title = `${n.label} ${stepName(n, s.sub_step)}\n${s.ts} · 无统计数据`;
      } else {
        bar.className = "gt-bar" + (isCur ? " cur" : "");
        bar.style.left = x + "px";
        bar.style.width = Math.max(3, Math.round(s.duration_s * scale)) + "px";
        bar.title =
          `${n.label} ${stepName(n, s.sub_step)}\n${s.ts} 起 · ` +
          `结束 ${fmtClockD(new Date(new Date(s.ts).getTime() + s.duration_s * 1000))} · ` +
          `耗时 ${s.duration_s}s · ` +
          `${fmtDur(s.num_turns)} 轮\ntok in ${s.input_tokens ?? "-"} / out ` +
          `${s.output_tokens ?? "-"}\n$${(s.cost_usd ?? 0).toFixed(3)}`;
        if (s.duration_s * scale > 68) {
          bar.textContent = `${stepName(n, s.sub_step)} ${s.duration_s}s·${fmtDur(s.num_turns)}轮`;
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

function renderTimeline(stats, nodes, info, artifacts, driverPid) {
  const box = $("timeline");
  const skin = tlSkin();
  box.classList.remove("metro", "gantt", "cards");
  box.classList.add(skin);
  // 总进度条：已完成 step / 可见 step（可见集 = 后端 scanner 单源过滤）
  const vis = nodes;
  const total = vis.reduce((a, n) => a + n.steps.length, 0);
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
  if (skin === "gantt") renderTimelineGantt(stats, nodes, info, artifacts, driverPid);
  else renderTimelineTree(stats, nodes, info, artifacts, driverPid);
  document.querySelectorAll("#tl-switch button").forEach((b) =>
    b.classList.toggle("on", b.dataset.skin === skin));
}

function renderInteract(d) {
  const box = $("interact");
  // SSE 每 2s 触发本区重建——先保住用户已选/已填，渲完恢复
  // （实爆：radio 选完 2 秒被轮询清掉）。同名多选（checkbox）存数组，
  // 单值存取会只剩最后一个勾选
  const savedChecks = {};
  box.querySelectorAll("input[type=radio]:checked, input[type=checkbox]:checked")
    .forEach((r) => {
      (savedChecks[r.name] = savedChecks[r.name] || []).push(r.value);
    });
  const savedOther = {};
  box.querySelectorAll("input[id$=-other]").forEach((i) => {
    savedOther[i.id] = i.value;
  });
  box.innerHTML = "";
  const proj = sel.project, name = sel.name;
  const mkBtn = (label, fn, cls) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = () => fn(b);
    b.className = cls || "btn";
    return b;
  };
  /* 慢操作 busy 态：转圈 + 禁用直到返回（inject 要等 30-120s——
     无反馈时用户会连点，三连 inject 实爆） */
  const busy = (b, label) => {
    b.disabled = true;
    const orig = b.innerHTML;
    b.innerHTML = `<span class="spinner"></span>${label}`;
    return () => { b.disabled = false; b.innerHTML = orig; };
  };
  if (d.answered) {
    // 已答窗口（dashboard-answered-marker-design §2.4）：标记覆盖当前问题卡
    // ——横幅替代表单，提交后按钮不再复活；新问题落盘/步骤推进自动切换
    const h = document.createElement("h3");
    h.textContent = "答案已提交";
    box.appendChild(h);
    const prep = document.createElement("div");
    prep.className = "q";
    prep.textContent = `${d.answered} 已注入——模型处理中，门控通过后自动推进下一步` +
      "（无需重复提交；需要你再答的新问题出现时会自动替换本卡）";
    box.appendChild(prep);
  } else if (d.injecting) {
    // inject 在飞（2026-09-18 实爆：提交后刷新页面表单复活——在飞标记
    // 落盘前「未提交」与「处理中」不可分）；服务端 injecting.json 单源
    const h = document.createElement("h3");
    h.textContent = "注入中";
    box.appendChild(h);
    const prep = document.createElement("div");
    prep.className = "q";
    prep.textContent = `答案注入中（${d.injecting} 起）——模型段回复要 1-2 分钟，` +
      "完成自动翻「已提交」（无需刷新/重复提交）";
    box.appendChild(prep);
  } else if (parked && parked.project === proj && parked.name === name &&
             d.need_user && d.need_user.ts === parked.ts) {
    // 答题排队暂存态（就绪自动注入由 refreshDetail 的 parked 生命周期执行）
    // inflight 区分显示（2026-09-17 实爆：注入 POST 在飞 1-3min 卡面停在
    // 「已暂存」，「未触发」与「注入中」不可分，用户误判延迟）
    const h = document.createElement("h3");
    h.textContent = parked.inflight ? "注入中" : "答案已暂存";
    box.appendChild(h);
    const prep = document.createElement("div");
    prep.className = "q";
    prep.textContent = parked.inflight
      ? "答案注入中——模型段回复要 1-2 分钟，完成自动翻「已提交」（无需刷新）"
      : "交互段就绪后自动注入——无需守等/刷新；问题若被更新暂存会自动作废（防答进错题）";
    box.appendChild(prep);
    if (!parked.inflight) {
      box.appendChild(mkBtn("取消暂存（重新作答）", () => {
        setParked(null);
        refreshDetail();
      }, "btn"));
    }
  } else if (d.need_user && d.need_user.questions) {
    const h = document.createElement("h3");
    h.textContent = "等待输入";
    box.appendChild(h);
    if (!d.inject_ready) {
      // 准备中窗口（问题已 stash 但注入段台账未落）：问题内容不再变，
      // 先作答=等待与答题并行（旧版锁表单纯等，qoder 冷段实爆）
      const prep = document.createElement("div");
      prep.className = "q";
      prep.textContent = d.driver_pid
        ? "交互段准备中——可先作答，就绪后自动注入（无需守等）"
        : "交互段未就绪且 driver 已停——点标题行「恢复驱动」；也可先作答，拉起后自动注入";
      box.appendChild(prep);
    }
    if (d.inject_error) {
      // inject 失败如实上报（异步受理后失败不再经 HTTP 返回——服务端标记
      // 错误态是唯一通道；表单照常渲染可直接重答）
      const errDiv = document.createElement("div");
      errDiv.className = "q";
      errDiv.style.color = "var(--err, #c00)";
      errDiv.textContent = `上次注入失败：${d.inject_error}——请重新作答提交`;
      box.appendChild(errDiv);
    }
    const answers = [];
    d.need_user.questions.forEach((q, i) => {
      const div = document.createElement("div");
      div.className = "q";
      div.innerHTML = `<b>[${esc(q.header || "Q" + (i + 1))}]</b> ${esc(q.question)}`;
      // multiSelect → checkbox（原一律 radio，多选题被压成单选——实爆）
      const inputType = q.multiSelect ? "checkbox" : "radio";
      (q.options || []).forEach((op) => {
        const l = document.createElement("label");
        l.innerHTML =
          `<input type="${inputType}" name="q${i}" value="${esc(op.label)}"> ` +
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
    const collect = () => answers.map((i) => {
      const q = d.need_user.questions[i];
      const checked = [...box.querySelectorAll(`input[name=q${i}]:checked`)]
        .map((r) => r.value);
      const other = $(`q${i}-other`).value.trim();
      const picked = q.multiSelect ? checked.join("；") : (checked[0] || "");
      return `问题${i + 1}：${other || picked || "（未选）"}`;
    }).join("\n");
    box.appendChild(mkBtn(
      d.inject_ready ? "提交答案" : "暂存答案（就绪后自动注入）",
      async (btn) => {
        if (!d.inject_ready) {
          // 暂存：不动服务端，refreshDetail 指纹含 parked 当场重渲暂存态
          setParked({ project: proj, name, ts: d.need_user.ts,
                      answer: collect(), inflight: false });
          toast("答案已暂存——交互段就绪后自动注入", true);
          refreshDetail();
          return;
        }
        const done2 = busy(btn, "注入中…（交互段回复要 1-2 分钟，勿重复点）");
        try {
          const r = await post("/api/inject",
            { project: proj, name, answer: collect() });
          toast(r.msg, r.ok);
          refreshDetail();
        } finally {
          done2();
        }
      }, "btn primary"));
  }
  const adv = document.createElement("details");
  adv.className = "dl-advanced";
  adv.innerHTML = `<summary>高级：/dl 阶段控制（纠偏用，日常不用点）</summary>`;
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
    toast(r.msg, r.ok); refreshDetail();
  });
  adv.appendChild(form); adv.appendChild(go);
  box.appendChild(adv);
  // 恢复重建前的选择与输入（同名多选逐个恢复）
  for (const [name, values] of Object.entries(savedChecks)) {
    for (const value of values) {
      const r = box.querySelector(`input[name=${name}][value="${CSS.escape(value)}"]`);
      if (r) r.checked = true;
    }
  }
  for (const [id, value] of Object.entries(savedOther)) {
    const i = box.querySelector(`#${id}`);
    if (i) i.value = value;
  }
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
      if (c.summary) {
        html += `<div class="cp-summary">${esc(c.summary)}</div>`;
      }
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

let lastDetailFp = "";

async function refreshDetail() {
  if (!sel.project) return;
  const r = await fetch(
    `/api/workflow?project=${encodeURIComponent(sel.project)}` +
    `&name=${encodeURIComponent(sel.name)}`);
  const d = await r.json();
  /* 答题排队生命周期（在任何渲染门之前跑——fp 不变也要判）：
     失效（问题集重 stash）→ 作废；就绪（inject_ready 翻面）→ 自动注入 */
  if (parked && parked.project === sel.project && parked.name === sel.name) {
    if (!d.need_user || d.need_user.ts !== parked.ts) {
      setParked(null);
      toast("问题已更新——暂存答案作废，请重新作答", false);
    } else if (!parked.inflight && d.inject_ready && !d.answered) {
      parked.inflight = true;
      const pr = await post("/api/inject",
        { project: parked.project, name: parked.name, answer: parked.answer });
      toast(pr.msg, pr.ok);
      // 失败重试一次（竞态窗口：就绪翻面到 POST 之间段态再变）；再失败放
      // 弃暂存，用户看到 toast 重答——防无限重试空转
      if (!pr.ok && (parked.retries || 0) < 1) {
        parked.inflight = false;
        setParked({ ...parked, retries: (parked.retries || 0) + 1 });
      } else {
        setParked(null);
      }
      return refreshDetail();  // 拉已答横幅/失败后的表单重渲
    }
  }
  /* 差异化刷新：指纹（updated_at/gate/held/need_user/driver/stats/log）变了才动
     静态面（标题/按钮/交互区/日志）；动态面（徽标/时间轴）只在 driver 活着时
     按拍刷（在跑计时/增长条），driver 停且无变化 = 完全不动。 */
  const fp = JSON.stringify([
    d.info.updated_at, d.info.gate, d.info.held_for_gate, d.info.need_user,
    d.driver_pid, d.log_tail.length, d.stats.length,
    d.stats.length ? d.stats[d.stats.length - 1].ts : "",
    // 直接依赖补登：已答标记翻面（注入/失效）与新题落盘（同 bool 不同 ts）
    // 必须当场重渲交互区——不等 updated_at/driver/log 间接触发
    d.answered, d.need_user && d.need_user.ts,
    // renderTimeline 直接输入补登（2026-09-01 实爆）：driver 死 + fp 恒定时
    // renderDetailLive 被跳过——换肤点击不重渲（得 F5 才生效）；产物装配/
    // 删除也不反映（产出物「又没有了」）。皮肤与产物 exists 都是渲染输入，
    // 不入指纹 = 输入变了不重渲
    localStorage.getItem("dl_tl_skin"),
    d.artifacts && d.artifacts.understands && d.artifacts.understands.exists,
    d.artifacts && d.artifacts.plans && d.artifacts.plans.exists,
    // 运行审计（evolution-up P1）：裁决/段账新增必须当场重渲审计区
    d.audit && d.audit.gates
      ? `${d.audit.gates.judged}:${d.audit.gates.blocked_total}` : "",
    d.totals && d.totals.cost_usd,
    // 插话（evolution-up P5）：新发/被消费翻面必须当场重渲列表
    d.steers ? d.steers.length + ":" + d.steers.filter((s) => s.consumed).length : 0,
    // 答题排队：暂存/取消必须当场重渲交互区（服务端数据不变，纯本地态）
    parked && parked.project === sel.project && parked.name === sel.name
      ? "parked:" + parked.ts + (parked.inflight ? ":inflight" : "") : "",
    // inject 在飞标记翻面（提交→刷新页面也要见「注入中」）当场重渲
    d.injecting, d.inject_error,
  ]);
  const changed = fp !== lastDetailFp;
  lastDetailFp = fp;
  if (changed) renderDetailStatic(d);
  if (changed || d.driver_pid) renderDetailLive(d);
}

function renderDetailStatic(d) {
  const modeTags = (d.info.force_tacet ? `<span class="tag mode-tacet">tacet</span>` : "") +
    (d.info.force_fermate ? `<span class="tag mode-fermate">fermate</span>` : "") +
    (d.info.gate === "done" ? `<span class="tag mode-done">已完结</span>` : "");
  $("d-title").innerHTML = `${esc(d.info.name)} · ${esc(d.info.node)}` +
    (d.info.gate === "done" ? "" :
      (d.driver_pid ? `（driver #${d.driver_pid}）` : "（driver 已停）")) + modeTags;
  renderInteract(d);
  $("log-tail").textContent = d.log_tail;
  renderAudit(d.audit, d.info.nodes);
  renderSteer(d.steers || []);
}

/* 插话通道（evolution-up P5）：段在跑期间的转向指令——落 steer.jsonl，
   下一个段起跑注入段 prompt（driver steer_consume）。不打断在跑段。 */
function renderSteer(steers) {
  const box = $("steer-list");
  box.innerHTML = steers.length
    ? "<ul class='steer-ul'>" + steers.map((s) =>
        `<li class="${s.consumed ? "steer-done" : "steer-pending"}">` +
        `<span class="num">${esc(s.ts)}</span> ${esc(s.text)}` +
        `<span class="hint">${s.consumed ? "已注入" : "待注入"}</span></li>`
      ).join("") + "</ul>"
    : "";
  const btn = $("steer-send");
  btn.onclick = async () => {
    const input = $("steer-text");
    const text = input.value.trim();
    if (!text) return;
    const r = await post("/api/steer", { project: sel.project, name: sel.name, text });
    toast(r.msg, r.ok);
    if (r.ok) input.value = "";
    refreshDetail();
  };
  $("steer-text").onkeydown = (e) => {
    if (e.key === "Enter") btn.click();
  };
}

/* 运行审计（evolution-up P1）：每轮运行的例行体检——一次通过率/block
   分布/节点成本/dispute 清单。数据 = /api/workflow 的 audit 键（audit.py
   纯读侧机械装配，零模型）。 */
function renderAudit(a, nodes) {
  // 中文步名映射：scanner step_labels 单源，与时间轴同口径（2026-09-17
  // 用户裁决：审计区禁裸 understand:1#1）；节点不在可见集回退裸 id
  const nmap = new Map((nodes || []).map((n) => [n.node_id, n]));
  const stepLabel = (nodeId, subStep) => {
    const n = nmap.get(nodeId);
    return n ? `${n.label}·${stepName(n, subStep)}` : `${nodeId}#${subStep}`;
  };
  const nodeLabel = (nodeId) => (nmap.get(nodeId) || {}).label || nodeId;
  const box = $("audit"), sum = $("audit-summary");
  if (!a || a.error) {
    sum.textContent = "";
    box.innerHTML = a && a.error
      ? `<div class="hint">审计数据暂缺：${esc(a.error)}</div>` : "";
    return;
  }
  const g = a.gates || { judged: 0, steps: [], disputes: [] };
  sum.textContent = g.judged
    ? `一次通过率 ${(g.first_pass_rate * 100).toFixed(0)}%` +
      `（${g.first_pass}/${g.judged} 步首判即过）· block ${g.blocked_total} 次`
    : "尚无门控裁决";
  let html = "";
  if (g.judged) {
    const STATUS = { passed: "过", blocked: "未过", confirm: "免判", unknown: "?" };
    html += '<table class="audit-tbl"><thead><tr>' +
      "<th>步骤</th><th>提交</th><th>block</th><th>状态</th><th>第几次过</th><th>末次判词</th>" +
      "</tr></thead><tbody>";
    for (const s of g.steps) {
      const cls = s.blocked ? "audit-blocked" : "audit-pass";
      html += `<tr class="${cls}"><td data-l="步骤">${esc(stepLabel(s.node, s.sub_step))}</td>` +
        `<td class="num" data-l="提交">${s.traces}</td><td class="num" data-l="block">${s.blocked}</td>` +
        `<td data-l="状态">${STATUS[s.status] || esc(s.status)}</td>` +
        `<td class="num" data-l="第几次过">${s.attempts_to_pass ?? "—"}</td>` +
        `<td class="audit-reason" data-l="末次判词">${esc(s.last_reason || "")}</td></tr>`;
    }
    html += "</tbody></table>";
  }
  if (g.disputes && g.disputes.length) {
    html += '<div class="audit-disputes"><b>判据申诉（rubric-dispute）：</b><ul>';
    for (const d of g.disputes) {
      html += `<li><span>${esc(stepLabel(d.node, d.sub_step))}</span> ${esc(d.reason)}</li>`;
    }
    html += "</ul></div>";
  }
  if (a.nodes && a.nodes.length) {
    html += '<table class="audit-tbl"><thead><tr>' +
      "<th>节点</th><th>段</th><th>轮</th><th>墙钟</th><th>成本</th>" +
      "<th>fresh in</th><th>cache read</th></tr></thead><tbody>";
    for (const n of a.nodes) {
      html += `<tr><td data-l="节点">${esc(nodeLabel(n.node))}</td>` +
        `<td class="num" data-l="段">${n.segments}</td><td class="num" data-l="轮">${n.turns}</td>` +
        `<td class="num" data-l="墙钟">${fmtHMS(n.duration_s)}</td>` +
        `<td class="num" data-l="成本">$${n.cost_usd}</td>` +
        `<td class="num" data-l="fresh in">${fmtTok(n.input_tokens)}</td>` +
        `<td class="num" data-l="cache read">${fmtTok(n.cache_read)}</td></tr>`;
    }
    html += "</tbody></table>";
  }
  box.innerHTML = html;
}

function renderDetailLive(d) {
  // 在跑徽标：当前步中文名 + 工作流总执行时间（Σ 已完成段 + 当前段已跑——
  // step 自己的时间只在当前跑步叶子上展示，不在这里）；SSE 2s 刷新
  const live = $("tl-live");
  const curNodeInfo = d.info.nodes.find((n) => n.status === "current");
  const curStepName = curNodeInfo
    ? `${curNodeInfo.label} ${stepName(curNodeInfo, d.info.sub_step_index)}` : "当前步";
  if (d.driver_pid) {
    // 总执行时间 = Σ 完成段耗时 + 在飞段实跑（current_segment.started_at——
    // driver 起跑落盘）。旧口径「末段结束 - now」把等用户答题时间也算入，
    // 且段结束时总数倒退（两实爆）；driver 停（等答/门栏）徽标不显示
    const totDur = d.stats.reduce((a, s) => a + (s.duration_s || 0), 0);
    const cs = d.info.current_segment;
    const curEl = cs && cs.started_at
      ? Math.max(0, Math.round((Date.now() - new Date(cs.started_at).getTime()) / 1000))
      : 0;
    live.innerHTML =
      `<span class="live-badge"><span class="dot ok"></span>在跑 · ${esc(curStepName)}` +
      ` · 总 ${fmtHMS(totDur + curEl)}</span>`;
  } else {
    live.textContent = "";
  }
  // 问题描述折叠（stmt-collapse）：>3 行默认收起，真溢出才给「展开全部」按钮
  const stmtEl = $("d-statement");
  stmtEl.textContent = d.info.problem_statement;
  _stmt_collapse_sync(stmtEl);
  // 标题行 gate 放行按钮（仅在可作用时显示——gate_actionable scanner 单源：
  // 门栏扣留 / 闸门后置阶段 pending；gate 从启动就是 pending，旧判定
  // 「held || pending」= 全程常显，点了报错）
  const done = d.info.gate === "done";
  const gb = $("gate-btn");
  gb.classList.toggle("hidden", done || !d.info.gate_actionable);
  gb.onclick = async () => {
    const r = await post("/api/gate", { project: sel.project, name: sel.name });
    toast(r.msg, r.ok);
    refreshDetail();
  };
  // 标题行暂停/恢复按钮（随 driver 状态切换）
  const pt = $("pause-toggle");
  pt.classList.toggle("hidden", done || (d.info.held_for_gate && !d.driver_pid));
  pt.textContent = d.driver_pid ? "暂停" : "恢复驱动";
  pt.onclick = async () => {
    const r = await post(d.driver_pid ? "/api/pause" : "/api/drive",
      { project: sel.project, name: sel.name });
    toast(r.msg, r.ok);
    refreshDetail();
  };
  renderTimeline(d.stats, d.info.nodes, d.info, d.artifacts, d.driver_pid);
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
let lastProviders = [];
let lastWorkflowNames = new Set();  // 已存在工作流名（生成名防碰撞用）

/* 从 problem_statement 提取英文关键词自动生成名称（≤5 词，_ 连接，≤63 字符）：
   提取拉丁 token -> 小写 -> 去停用词（含疑问词/泛化动词套话）-> 去重；
   候选超 5 个时按词长优选（长词信息量高），再恢复原语句序保持可读；
   纯中文陈述提取不出词则留空，名称框可手填。
   名称正则约束 ^[a-z0-9][a-z0-9_-]{0,63}$（与后端 _NAME_RE 一致）。 */
const NAME_STOP = new Set([
  "the", "a", "an", "of", "for", "and", "or", "is", "are", "to", "in", "on",
  "we", "our", "you", "your", "this", "that", "it", "its", "be", "by", "at",
  "as", "if", "so", "no", "not", "do", "does", "did", "has", "have", "had",
  /* 疑问词 + 泛化动词/套话：高频但不携带问题主题 */
  "why", "how", "what", "when", "where", "which", "who", "please", "help",
  "want", "need", "make", "get", "use", "using", "fix", "add", "create",
  "change", "update", "bug", "issue", "problem", "error", "fail", "failed",
  "can", "could", "should", "would", "will", "just", "like", "know", "think",
  "see", "look", "run", "running", "way", "too", "very", "much", "more",
  "some", "any", "all", "than", "then", "them", "they", "there", "here",
  "with", "from", "about", "after", "before", "while", "also", "still",
  "even", "only", "same", "now", "new", "seems", "me", "my", "us", "let",
  "between", "investigate", "analyze", "analyse", "check",
]);
const NAME_MAX_WORDS = 5;
const NAME_MAX_LEN = 63;
const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
function genName(statement) {
  const words = (statement.match(/[a-zA-Z][a-zA-Z0-9]*/g) || [])
    .map((w) => w.toLowerCase())
    .filter((w) => !NAME_STOP.has(w) && w.length > 1);
  const uniq = [...new Set(words)];
  /* 候选超上限：按词长（信息量代理）优选，再按原语序排回——名称仍读得出原句结构 */
  const picked = uniq.length <= NAME_MAX_WORDS
    ? uniq
    : [...uniq]
        .sort((a, b) => b.length - a.length)
        .slice(0, NAME_MAX_WORDS)
        .sort((a, b) => uniq.indexOf(a) - uniq.indexOf(b));
  /* 逐词拼接、整词截断：避免 slice 切出半个词或尾部下划线 */
  let name = "";
  for (const w of picked) {
    const cand = name ? `${name}_${w}` : w;
    if (cand.length > NAME_MAX_LEN) break;
    name = cand;
  }
  return name;
}
/* 名称预览 = 防重后的最终名（所见即所建）：生成 -> 撞现存名自动 _2/_3；
   用户手改过的名字不被后续输入覆盖（值等于上次生成结果才视为未手改） */
let lastGenName = "";
function previewName() {
  const cur = $("cf-name").value;
  if (cur && cur !== lastGenName) return;
  const base = genName($("cf-statement").value);
  lastGenName = base ? dedupeName(base) : "";
  $("cf-name").value = lastGenName;
}
$("cf-statement").addEventListener("input", previewName);

/* 提交时定名：以输入框为准（预览已填入，用户可手改）-> 空则拦 -> 防碰撞加 _2/_3 后缀 */
function dedupeName(base) {
  if (!lastWorkflowNames.has(base)) return base;
  for (let i = 2; ; i++) {
    const cand = `${base}_${i}`;
    if (!lastWorkflowNames.has(cand)) return cand;
  }
}

function openCreateModal() {
  // datalist 提供历史候选；输入框可自由填路径。localStorage 记住上次选择。
  $("cf-projects").innerHTML = lastProjects.map((p) =>
    `<option value="${esc(p)}">`).join("");
  $("cf-project").value =
    localStorage.getItem("dl-last-project") || lastProjects[0] || "";
  $("cf-provider").innerHTML =
    `<option value="">server 当前环境（默认）</option>` +
    lastProviders.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
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

/* 引擎卡（per-instance-engine）：异步渲染，逐卡绑 onclick（上面的静态绑定
   覆盖不到）；claude 默认选中；单引擎机器只一张卡；空列表不渲染零行为变化 */
async function initEngineCards() {
  const row = $("engine-cards");
  const r = await fetch("/api/engines");
  const data = await r.json().catch(() => ({}));
  const engines = (data && data.engines) || [];
  row.innerHTML = "";
  const LABELS = {
    claude: ["claude", "Claude Code 后端（默认）"],
    qodercli: ["qoder", "Qoder CLI 后端（dl @qoder）"],
  };
  engines.forEach((eng, i) => {
    const [title, desc] = LABELS[eng] || [eng, eng];
    const card = document.createElement("div");
    card.className = "mode-card" + (i === 0 ? " sel" : "");
    card.dataset.v = eng;
    card.innerHTML = `<b>${esc(title)}</b><span>${esc(desc)}</span>`;
    card.onclick = () => {
      row.querySelectorAll(".mode-card").forEach((x) => x.classList.remove("sel"));
      card.classList.add("sel");
      syncProviderForEngine();
    };
    row.appendChild(card);
  });
  syncProviderForEngine();
}
initEngineCards().catch((err) => console.warn("engine cards unavailable:", err));

function currentEngine() {
  return document.querySelector("#engine-cards .mode-card.sel")?.dataset.v || "claude";
}

function syncProviderForEngine() {
  const sel = $("cf-provider");
  const qoder = currentEngine() === "qodercli";
  sel.disabled = qoder;  // provider=claude 系 ac-* env，qoder 不适用
  sel.title = qoder ? "qoder 引擎不使用 provider（模型由向导选中或 DL_QODER_MODEL 定）" : "";
}

$("create-form").onsubmit = async (e) => {
  e.preventDefault();
  // 创建中禁重复提交（launcher --setup-only 建实例要几秒——无反馈时用户会连点，
  // per-workflow 锁在服务端兜底，前端先拦）
  const submitBtn = $("create-form").querySelector("button[type=submit]");
  if (submitBtn.disabled) return;
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span class="spinner"></span>创建中…`;
  const restore = () => {
    submitBtn.disabled = false;
    submitBtn.textContent = "创建并启动";
  };
  const statement = $("cf-statement").value.trim();
  // 名称以输入框为准（预览已填入生成名，用户可手改；纯中文陈述生成不出时手填）
  const base = $("cf-name").value.trim() || genName(statement);
  if (!base) {
    toast("无法生成工作流名——请手填名称，或在问题中包含英文关键词（如因子名/页面名）", false);
    restore();
    return;
  }
  if (!NAME_RE.test(base)) {
    toast("名称只能含小写字母/数字/_/-，且以字母或数字开头（≤63 字符）", false);
    restore();
    return;
  }
  const name = dedupeName(base);  // 提交时重防撞（名单可能刚变）
  const scope = document.querySelector("#scope-cards .mode-card.sel").dataset.v;
  const tacet = document.querySelector("#track-cards .mode-card.sel").dataset.v === "tacet";
  try {
    localStorage.setItem("dl-last-project", $("cf-project").value.trim());
    const r = await post("/api/create", {
      project: $("cf-project").value.trim(),
      name,
      statement,
      scope,
      tacet,
      provider: $("cf-provider").value || null,
      engine: currentEngine(),
    });
    toast(r.ok ? `已创建 ${name}` : r.msg, r.ok);
    if (r.ok) closeCreateModal();
  } finally {
    restore();
  }
};

document.querySelectorAll("#tl-switch button").forEach((b) => {
  b.onclick = () => {
    localStorage.setItem("dl_tl_skin", b.dataset.skin);
    refreshDetail();
  };
});

let lastSidebarJson = "";
function handleSnapshot(data) {
  lastProjects = data.projects || [];
  lastProviders = data.providers || [];
  lastWorkflowNames = new Set(data.workflows.map((w) => w.name));
  TabAlert.check(data.workflows);
  // 侧栏指纹：数据没变就不重建（选中高亮在 selectWorkflow 里即时翻 class）
  const sj = JSON.stringify(data.workflows);
  if (sj !== lastSidebarJson) {
    lastSidebarJson = sj;
    renderSidebar(data.workflows);
  }
  if (sel.project) refreshDetail();
}
const es = new EventSource("/api/events");
let lastEsMsg = Date.now();
es.onmessage = (e) => {
  lastEsMsg = Date.now();
  handleSnapshot(JSON.parse(e.data));
};
/* SSE 断流降级轮询：代理/隧道缓冲长连接时 onmessage 静默断流（连接看似
   开着但数据永不到达，onerror 不一定触发——公网地址访问实爆：状态全靠
   手动刷新）。SSE 节拍 2s，15s 无消息即判死，10s 轮询 /api/workflows 兜底；
   SSE 恢复（重连成功 onmessage 复跳）后 lastEsMsg 刷新，轮询自动静默。 */
setInterval(async () => {
  if (Date.now() - lastEsMsg < 15000) return;
  try {
    const r = await fetch("/api/workflows");
    if (r.ok) handleSnapshot(await r.json());
  } catch (e) { /* 网络抖动下轮继续 */ }
}, 10000);

/* ---------- 页签关注提醒：标题闪动 + favicon 红点（tab-attention-alert-design） ----------
   触发=SSE workflows 状态跃迁：isWaiting 进入=🔔待确认 / gate=done 进入=✅已完结。
   首轮静默播种；标题闪动仅 document.hidden 时；favicon 计数=waiting+完结未读。 */
const TabAlert = (() => {
  const ORIG_TITLE = document.title;
  const prev = new Map();      // key -> "wait"|"done"|""（上一轮状态）
  const doneUnread = new Set(); // 完结未读（仅页签隐藏时记录，重获焦点清空）
  let lastList = [];
  let seeded = false;
  let flashTimer = null;

  const key = (w) => `${w.project}/${w.name}`;
  const kindOf = (w) => {
    if (w.error) return "";
    if (isWaiting(w)) return "wait";
    if (w.gate === "done") return "done";
    return "";
  };
  const shortName = (k) => k.split("/").pop();

  function setFavicon(dataUrl) {
    let link = document.querySelector('link[rel="icon"][data-tabalert]');
    if (!dataUrl) {
      link?.remove(); // 移除动态 link，回退默认 /favicon.ico
      return;
    }
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      link.dataset.tabalert = "1";
      document.head.appendChild(link);
    }
    link.href = dataUrl;
  }

  function paintBadge(n) {
    if (n <= 0) { setFavicon(null); return; }
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const g = c.getContext("2d");
    g.fillStyle = "#e5484d";
    g.beginPath(); g.arc(32, 32, 30, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#fff";
    g.font = "bold 34px sans-serif";
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(n > 9 ? "9+" : String(n), 32, 35);
    setFavicon(c.toDataURL("image/png"));
  }

  function badgeCount() {
    return lastList.filter((w) => kindOf(w) === "wait").length + doneUnread.size;
  }

  function stopFlash() {
    if (flashTimer) { clearInterval(flashTimer); flashTimer = null; }
    if (document.title !== ORIG_TITLE) document.title = ORIG_TITLE;
  }

  function startFlash(text) {
    if (!document.hidden) return; // 人正盯着页面，卡片就在眼前，闪动=骚扰
    stopFlash();
    let on = false;
    document.title = text;
    flashTimer = setInterval(() => {
      on = !on;
      document.title = on ? text : ORIG_TITLE;
    }, 1200);
  }

  function check(list) {
    lastList = list;
    const now = new Map(list.map((w) => [key(w), kindOf(w)]));
    for (const k of [...doneUnread]) if (!now.has(k)) doneUnread.delete(k);
    if (!seeded) { // 首轮静默播种：存量待办不闪，只落 badge
      seeded = true;
      now.forEach((v, k) => prev.set(k, v));
      paintBadge(badgeCount());
      return;
    }
    const alerts = [];
    now.forEach((cur, k) => {
      const before = prev.get(k) || "";
      if (cur === "wait" && before !== "wait") {
        alerts.push({ icon: "🔔", text: `${shortName(k)} 待确认` });
      }
      if (cur === "done" && before !== "done") {
        alerts.push({ icon: "✅", text: `${shortName(k)} 已完结` });
        // 人正盯着=卡片上已见，不记未读（同 startFlash「不骚扰」守卫）——
        // 缺此守卫时：页签一直可见的用户 doneUnread 只增不清，红 badge 永久常亮
        if (document.hidden) doneUnread.add(k);
      }
    });
    prev.clear(); now.forEach((v, k) => prev.set(k, v));
    paintBadge(badgeCount());
    if (!alerts.length) return;
    const last = alerts[alerts.length - 1];
    const text = alerts.length > 1
      ? `${last.icon} ${alerts.length} 项待处理 - dl dashboard`
      : `${last.icon} ${last.text} - dl dashboard`;
    startFlash(text);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    stopFlash();
    doneUnread.clear(); // 回来看过=完结已读
    paintBadge(badgeCount());
  });

  return { check };
})();
