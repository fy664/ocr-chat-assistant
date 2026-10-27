/* ============================================================
   聊天语义助手 · 产品介绍页
   交互：滚动揭示 / 计数器 / 演示流水线 / 复制 / FAQ / 代码页签
   ============================================================ */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("js");

  var $ = function (sel, ctx) { return (ctx || document).querySelector(sel); };
  var $$ = function (sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); };
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia("(pointer: fine)").matches;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function sleep(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function nowTime() {
    var d = new Date();
    return [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map(function (n) { return String(n).padStart(2, "0"); })
      .join(":");
  }
  function nowShort() {
    var d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  /* ---------------- toast ---------------- */
  var toastEl = $("#toast");
  var toastTimer = 0;
  function toast(message) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toastEl.classList.remove("is-visible");
    }, 2600);
  }

  /* ---------------- copy ---------------- */
  function legacyCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () {
        return legacyCopy(text);
      });
    }
    return Promise.resolve(legacyCopy(text));
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var text = button.getAttribute("data-copy") || "";
    copyText(text).then(function (ok) {
      if (!ok) { toast("复制失败，请手动选择"); return; }
      toast("已复制：" + (text.length > 26 ? text.slice(0, 26) + "…" : text));
      var isMini = button.classList.contains("copy-mini");
      var original = button.textContent;
      button.classList.add("is-done");
      if (isMini) button.textContent = "已复制";
      window.setTimeout(function () {
        button.classList.remove("is-done");
        if (isMini) button.textContent = original;
      }, 1500);
    });
  });

  /* ---------------- marquee ---------------- */
  var marquee = $("#marqueeTrack");
  if (marquee) marquee.innerHTML += marquee.innerHTML;

  /* ---------------- reveal ---------------- */
  var revealEls = $$(".reveal");
  if ("IntersectionObserver" in window && !reduceMotion) {
    var revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    revealEls.forEach(function (el) { revealObserver.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("is-visible"); });
  }

  /* ---------------- counters ---------------- */
  var counters = $$("[data-count]");
  function animateCount(el) {
    var target = parseInt(el.getAttribute("data-count"), 10) || 0;
    if (reduceMotion || target === 0) { el.textContent = String(target); return; }
    var start = performance.now();
    var duration = 1300;
    function frame(now) {
      var t = Math.min(1, (now - start) / duration);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = String(Math.round(target * eased));
      if (t < 1) requestAnimationFrame(frame);
      else el.textContent = String(target);
    }
    requestAnimationFrame(frame);
  }
  if (counters.length) {
    if ("IntersectionObserver" in window) {
      var counterObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          animateCount(entry.target);
          counterObserver.unobserve(entry.target);
        });
      }, { threshold: 0.6 });
      counters.forEach(function (el) { counterObserver.observe(el); });
    } else {
      counters.forEach(animateCount);
    }
  }

  /* ---------------- header / scroll ---------------- */
  var header = $("#siteHeader");
  var progressBar = $("#scrollBar");
  var toTop = $("#toTop");
  var sections = ["demo", "features", "architecture", "privacy", "start", "faq"]
    .map(function (id) { return document.getElementById(id); })
    .filter(Boolean);
  var navAnchors = $$("#navLinks a");
  var ticking = false;

  function setActiveNav() {
    var marker = window.scrollY + 140;
    var current = "";
    sections.forEach(function (section) {
      if (section.offsetTop <= marker) current = section.id;
    });
    navAnchors.forEach(function (link) {
      link.classList.toggle("is-active", link.getAttribute("href") === "#" + current);
    });
  }

  function onScroll() {
    var y = window.scrollY || window.pageYOffset;
    if (header) header.classList.toggle("is-scrolled", y > 16);
    if (toTop) toTop.classList.toggle("is-visible", y > 760);
    if (progressBar) {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      progressBar.style.width = (max > 0 ? Math.min(100, (y / max) * 100) : 0) + "%";
    }
    setActiveNav();
    ticking = false;
  }

  window.addEventListener("scroll", function () {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(onScroll);
  }, { passive: true });
  onScroll();

  if (toTop) {
    toTop.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
    });
  }

  /* ---------------- mobile nav ---------------- */
  var navToggle = $("#navToggle");
  if (navToggle && header) {
    navToggle.addEventListener("click", function () {
      var open = header.classList.toggle("nav-open");
      navToggle.setAttribute("aria-expanded", String(open));
      navToggle.setAttribute("aria-label", open ? "关闭导航菜单" : "打开导航菜单");
    });
    $$("#navLinks a").forEach(function (link) {
      link.addEventListener("click", function () {
        header.classList.remove("nav-open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
    document.addEventListener("click", function (event) {
      if (!header.classList.contains("nav-open")) return;
      if (header.contains(event.target)) return;
      header.classList.remove("nav-open");
      navToggle.setAttribute("aria-expanded", "false");
    });
  }

  /* ---------------- cursor glow ---------------- */
  var glow = $(".cursor-glow");
  if (glow && finePointer && !reduceMotion) {
    var glowQueued = false;
    var gx = 0, gy = 0;
    document.addEventListener("pointermove", function (event) {
      gx = event.clientX;
      gy = event.clientY;
      document.body.classList.add("has-pointer");
      if (glowQueued) return;
      glowQueued = true;
      requestAnimationFrame(function () {
        glow.style.setProperty("--mx", gx + "px");
        glow.style.setProperty("--my", gy + "px");
        glowQueued = false;
      });
    }, { passive: true });
  }

  /* ---------------- hero tilt ---------------- */
  var heroVisual = $(".hero-visual");
  var heroWindow = $("#heroWindow");
  if (heroWindow && finePointer && !reduceMotion) {
    heroWindow.addEventListener("pointermove", function (event) {
      var rect = heroVisual.getBoundingClientRect();
      var px = (event.clientX - rect.left) / rect.width - 0.5;
      var py = (event.clientY - rect.top) / rect.height - 0.5;
      heroWindow.style.transition = "transform 80ms linear";
      heroWindow.style.transform =
        "rotateY(" + (-7 + px * 6).toFixed(2) + "deg) rotateX(" + (3 - py * 5).toFixed(2) +
        "deg) rotateZ(-1.2deg)";
    });
    heroWindow.addEventListener("pointerleave", function () {
      heroWindow.style.transition = "";
      heroWindow.style.transform = "";
    });
  }

  /* ---------------- code tabs ---------------- */
  var codeTabs = $$(".code-tab");
  codeTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      var target = tab.getAttribute("data-tab");
      codeTabs.forEach(function (other) {
        var active = other === tab;
        other.classList.toggle("is-active", active);
        other.setAttribute("aria-selected", String(active));
      });
      $$(".code-pane").forEach(function (pane) {
        var active = pane.getAttribute("data-pane") === target;
        pane.classList.toggle("is-active", active);
        pane.hidden = !active;
      });
    });
  });

  /* ---------------- faq ---------------- */
  $$(".faq-q").forEach(function (button) {
    button.addEventListener("click", function () {
      var item = button.closest(".faq-item");
      var open = item.classList.toggle("is-open");
      button.setAttribute("aria-expanded", String(open));
    });
  });

  /* ---------------- desktop protocol launch ---------------- */
  var launchLink = $("#launchDesktop");
  if (launchLink) {
    launchLink.addEventListener("click", function () {
      toast("正在唤起桌面端… 若无反应，请先运行 .\\web\\register-protocol.ps1");
    });
  }

  /* ============================================================
     交互演示：模拟 OCR → 差异 → 防抖 → 模型 → 面板
     ============================================================ */
  var SCRIPT = [
    {
      lines: 2,
      ocrMs: 19,
      messages: [
        { from: "them", text: "在忙吗？" },
        { from: "me", text: "刚开完会" }
      ],
      analysis: {
        surface: "对方在确认你是否方便回应，语气简短，留有余地。",
        intent: ["确认你的可用时间", "为后续请求做铺垫", "避免显得打扰"],
        emotion: { label: "平静 · 试探", confidence: 0.62, evidence: "短句 + 问号，没有情绪词" },
        needs: ["希望得到一个明确回复", "不想被已读不回"],
        strategy: "先回应时间状态，再把话题交回去；避免只回一个「在」。",
        uncertainty: "缺少上下文，无法判断对方想聊什么。",
        replies: [
          { style: "轻松", text: "在的，刚好在摸鱼，怎么啦？" },
          { style: "直接", text: "有空，你说～" },
          { style: "体贴", text: "刚忙完，正好想找人说话。" }
        ]
      }
    },
    {
      lines: 3,
      ocrMs: 23,
      diff: "新增 1 行 · CHANGED",
      messages: [
        { from: "them", text: "你周末有空吗？那个新展好像快结束了" }
      ],
      analysis: {
        surface: "对方在提出具体的周末邀约，并用「快结束了」轻轻加了一点时间压力。",
        intent: ["邀请你周末一起看展", "试探你对这件事的兴趣", "希望尽快把时间定下来"],
        emotion: { label: "期待 · 轻微紧张", confidence: 0.71, evidence: "具体时间 + 主动补充理由" },
        needs: ["得到一个明确答复", "不想显得太主动"],
        strategy: "先给态度，再给候选时段；不确定时也给一个时间范围。",
        uncertainty: "无法确认展览的地点、票价与所需时长。",
        replies: [
          { style: "轻快", text: "有空！周六下午怎么样？" },
          { style: "保留", text: "应该可以，等我确认下时间～" },
          { style: "共情", text: "你居然记得我喜欢这个，那就去呗。" }
        ]
      }
    },
    {
      lines: 4,
      ocrMs: 26,
      diff: "新增 2 行 · CHANGED",
      messages: [
        { from: "me", text: "我确认下时间，别急" },
        { from: "them", text: "算了，你好像很忙，我自己去吧" }
      ],
      analysis: {
        surface: "对方把「没立刻答应」理解成拒绝，用「算了」把自己退回去，同时留了一个被挽留的出口。",
        intent: ["表达失落并准备退出邀约", "希望被认真挽留", "降低被拒绝的难受"],
        emotion: { label: "失落 · 防御", confidence: 0.83, evidence: "「算了」+ 自我抽离的表述" },
        needs: ["被认真对待", "明确而非模糊的回应"],
        strategy: "先接住情绪，再澄清事实；不要长篇解释，也不要立刻道歉了事。",
        uncertainty: "无法确定对方是真的不想去，还是在等一个台阶。",
        replies: [
          { style: "安抚", text: "别算了，我刚在开会没看手机，周六我请你喝咖啡。" },
          { style: "澄清", text: "不是不想去，是想跟你一起去，给我十分钟确认时间。" },
          { style: "轻快", text: "谁说我忙了？票你买还是我买？" }
        ]
      }
    }
  ];

  var demo = {
    el: null,
    index: 0,
    gen: 1,
    busy: false,
    token: 0
  };

  function cacheDemo() {
    demo.el = {
      chat: $("#chatScroll"),
      cards: $("#panelCards"),
      log: $("#logBody"),
      gen: $("#panelGen"),
      stepper: $("#stepper"),
      updating: $("#updatingBar"),
      next: $("#simNext"),
      scroll: $("#simScroll"),
      status: $("#demoStatus")
    };
    return demo.el.chat && demo.el.cards && demo.el.next;
  }

  function setDemoStatus(text) {
    if (demo.el && demo.el.status) demo.el.status.textContent = text;
  }

  function analysisHTML(a) {
    var pct = Math.round((a.emotion.confidence || 0) * 100);
    var intent = a.intent.map(function (item) { return "<li>" + esc(item) + "</li>"; }).join("");
    var needs = a.needs.map(function (item) { return "<li>" + esc(item) + "</li>"; }).join("");
    var replies = a.replies.map(function (reply) {
      return '<li><span class="reply-style">' + esc(reply.style) + "</span><p>" + esc(reply.text) +
        '</p><button class="copy-mini" type="button" data-copy="' + esc(reply.text) + '">复制</button></li>';
    }).join("");

    return [
      '<article class="acard acard-surface" style="--i:0">',
      '<header><span class="acard-dot"></span>当前理解</header>',
      "<p>" + esc(a.surface) + "</p>",
      "</article>",

      '<article class="acard acard-intent" style="--i:1">',
      '<header><span class="acard-dot"></span>可能意图</header>',
      '<ul class="pill-list">' + intent + "</ul>",
      "</article>",

      '<div class="acard-row">',
      '<article class="acard acard-emotion" style="--i:2">',
      '<header><span class="acard-dot"></span>情绪</header>',
      '<div class="emo"><span class="emo-ring" style="--v:' + (a.emotion.confidence || 0) + '"><span>' + pct + '%</span></span>',
      '<div class="emo-meta"><strong>' + esc(a.emotion.label) + "</strong><span>依据：" + esc(a.emotion.evidence) + "</span></div></div>",
      "</article>",
      '<article class="acard acard-needs" style="--i:3">',
      '<header><span class="acard-dot"></span>潜在诉求</header>',
      "<ul>" + needs + "</ul>",
      "</article>",
      "</div>",

      '<article class="acard acard-strategy" style="--i:4">',
      '<header><span class="acard-dot"></span>建议策略</header>',
      "<p>" + esc(a.strategy) + "</p>",
      "</article>",

      '<article class="acard acard-uncertainty" style="--i:5">',
      '<header><span class="acard-dot"></span>不确定性</header>',
      "<p>" + esc(a.uncertainty) + "</p>",
      "</article>",

      '<article class="acard acard-replies" style="--i:6">',
      '<header><span class="acard-dot"></span>回复建议</header>',
      '<ul class="reply-list">' + replies + "</ul>",
      "</article>"
    ].join("");
  }

  function renderAnalysis(analysis) {
    if (!demo.el) return;
    demo.el.cards.innerHTML = analysisHTML(analysis);
    demo.el.cards.scrollTop = 0;
  }

  function messageHTML(message) {
    var isMe = message.from === "me";
    var avatar = isMe ? "" : '<span class="msg-avatar">澈</span>';
    return '<div class="msg ' + (isMe ? "msg-me" : "msg-them") + '">' + avatar +
      '<div class="msg-col"><div class="msg-bubble">' + esc(message.text) + "</div>" +
      '<span class="msg-time">' + nowShort() + "</span></div></div>";
  }

  function appendMessage(message) {
    if (!demo.el) return;
    var template = document.createElement("template");
    template.innerHTML = messageHTML(message);
    demo.el.chat.appendChild(template.content.firstElementChild);
    demo.el.chat.scrollTo({ top: demo.el.chat.scrollHeight, behavior: reduceMotion ? "auto" : "smooth" });
  }

  function addLog(tag, text, cls) {
    if (!demo.el) return;
    var line = document.createElement("div");
    line.className = "log-line " + (cls || "");
    line.innerHTML = '<span class="log-time">' + nowTime() + '</span><span class="log-tag">' +
      esc(tag) + '</span><span class="log-text">' + esc(text) + "</span>";
    demo.el.log.appendChild(line);
    while (demo.el.log.children.length > 60) demo.el.log.removeChild(demo.el.log.firstElementChild);
    demo.el.log.scrollTop = demo.el.log.scrollHeight;
  }

  var STEP_ORDER = ["ocr", "diff", "debounce", "llm", "ui"];
  function setStep(name) {
    if (!demo.el) return;
    var index = STEP_ORDER.indexOf(name);
    $$("li", demo.el.stepper).forEach(function (item, i) {
      item.classList.toggle("is-done", i < index);
      item.classList.toggle("is-active", i === index);
    });
  }
  function finishSteps() {
    if (!demo.el) return;
    $$("li", demo.el.stepper).forEach(function (item) {
      item.classList.remove("is-active");
      item.classList.add("is-done");
    });
  }
  function resetSteps() {
    if (!demo.el) return;
    $$("li", demo.el.stepper).forEach(function (item) {
      item.classList.remove("is-active", "is-done");
    });
  }

  function setUpdating(on, label) {
    if (!demo.el || !demo.el.updating) return;
    demo.el.updating.hidden = !on;
    if (on && label) {
      var text = demo.el.updating.querySelector(".updating-label");
      if (text) text.textContent = label;
    }
  }

  function updateDemoButton() {
    if (!demo.el) return;
    var label = demo.el.next.querySelector("span");
    var atEnd = demo.index >= SCRIPT.length - 1;
    if (label) label.textContent = atEnd ? "重新演示" : "对方发来新消息";
    demo.el.next.setAttribute("aria-label", atEnd ? "重新开始交互演示" : "模拟对方发来新消息");
  }

  function resetDemo(quiet) {
    if (!demo.el) return;
    demo.token += 1;
    demo.busy = false;
    demo.index = 0;
    demo.gen = 1;
    demo.el.next.disabled = false;
    if (demo.el.scroll) demo.el.scroll.disabled = false;
    setUpdating(false);
    resetSteps();
    demo.el.gen.classList.remove("is-live");
    demo.el.gen.textContent = "generation #1";

    Array.prototype.slice.call(demo.el.chat.children).forEach(function (child) {
      if (!child.classList.contains("chat-day")) child.remove();
    });
    SCRIPT[0].messages.forEach(function (message) {
      var template = document.createElement("template");
      template.innerHTML = messageHTML(message);
      demo.el.chat.appendChild(template.content.firstElementChild);
    });
    demo.el.chat.scrollTop = demo.el.chat.scrollHeight;

    renderAnalysis(SCRIPT[0].analysis);
    demo.el.log.innerHTML = "";
    addLog("INIT", "监听开始 · 区域 820 × 560 · 仅内存", "log-cyan");
    addLog("OCR", "采样完成 · 2 行 · 19ms", "log-cyan");
    addLog("DIFF", "SCROLL_ONLY · 上下文更新，不触发模型", "log-amber");
    addLog("LLM", "generation=1 · Mock 客户端返回", "log-pink");
    addLog("UI", "首份分析已就绪", "log-green");
    setDemoStatus("演示已就绪，点击按钮模拟新消息。");

    updateDemoButton();
    if (!quiet) toast("演示已重置");
  }

  async function runTurn(nextIndex) {
    if (!demo.el || demo.busy) return;
    demo.busy = true;
    var token = ++demo.token;
    var turn = SCRIPT[nextIndex];
    demo.el.next.disabled = true;
    if (demo.el.scroll) demo.el.scroll.disabled = true;

    function alive() { return token === demo.token; }

    try {
      resetSteps();
      setStep("ocr");
      addLog("OCR", "采样完成 · " + turn.lines + " 行 · " + turn.ocrMs + "ms", "log-cyan");
      setDemoStatus("检测到新内容，正在识别文本。");

      for (var i = 0; i < turn.messages.length; i += 1) {
        await sleep(i === 0 ? 180 : 420);
        if (!alive()) return;
        appendMessage(turn.messages[i]);
      }

      await sleep(260);
      if (!alive()) return;
      setStep("diff");
      addLog("DIFF", turn.diff || "CHANGED · 行集合发生变化", "log-amber");

      await sleep(620);
      if (!alive()) return;
      setStep("debounce");
      addLog("DEBOUNCE", "文本已稳定 · 等待 700ms 后触发", "log-violet");

      await sleep(860);
      if (!alive()) return;
      setStep("llm");
      demo.gen += 1;
      demo.el.gen.textContent = "generation #" + demo.gen;
      demo.el.gen.classList.add("is-live");
      setUpdating(true, "正在更新分析…");
      addLog("LLM", "请求中 · generation=" + demo.gen + " · max 1 在途", "log-pink");
      setDemoStatus("正在请求语义分析，旧结果继续显示。");

      await sleep(1350);
      if (!alive()) return;
      addLog("SCHEMA", "Pydantic 校验通过 · surface / intent / emotion / needs / strategy / replies / uncertainty", "log-green");
      renderAnalysis(turn.analysis);

      setStep("ui");
      setUpdating(false);
      demo.el.gen.classList.remove("is-live");
      addLog("UI", "结果已原子替换 · 更新期间旧结果保持可见", "log-cyan");
      setDemoStatus("分析已更新，共三条回复建议。");

      await sleep(420);
      if (!alive()) return;
      finishSteps();
      demo.index = nextIndex;
      demo.busy = false;
      updateDemoButton();
      toast("分析已更新 · generation #" + demo.gen);
    } finally {
      if (alive()) {
        demo.busy = false;
        demo.el.next.disabled = false;
        if (demo.el.scroll) demo.el.scroll.disabled = false;
      }
    }
  }

  function simulateScroll() {
    if (!demo.el || demo.busy) return;
    addLog("OCR", "采样完成 · 4 行 · 22ms", "log-cyan");
    addLog("DIFF", "SCROLL_ONLY · 纯滚动，指纹未变", "log-amber");
    addLog("CTX", "上下文已合并 · 未调用模型", "log-violet");
    setDemoStatus("纯滚动仅更新上下文，未调用模型。");
    var dot = demo.el.gen;
    dot.classList.add("is-live");
    window.setTimeout(function () { dot.classList.remove("is-live"); }, 900);
    toast("纯滚动：只更新上下文，不调用模型");
  }

  if (cacheDemo()) {
    resetDemo(true);
    demo.el.next.addEventListener("click", function () {
      if (demo.busy) return;
      if (demo.index >= SCRIPT.length - 1) {
        resetDemo(false);
        return;
      }
      runTurn(demo.index + 1);
    });
    if (demo.el.scroll) demo.el.scroll.addEventListener("click", simulateScroll);
  }
})();
