/* ============================================================
   聊天语义助手 · 产品介绍页
   交互：滚动揭示 / 计数器 / 复制 / FAQ / 代码页签
   ============================================================ */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("js");

  var $ = function (sel, ctx) { return (ctx || document).querySelector(sel); };
  var $$ = function (sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); };
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia("(pointer: fine)").matches;

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
  var sections = ["features", "architecture", "privacy", "start", "faq"]
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
})();
