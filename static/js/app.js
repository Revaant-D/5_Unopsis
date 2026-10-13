/* =======================================================================================
   app.js -- the small behaviours of the wireframe UI. No framework and no build step.
   Every feature is opt-in through a data- attribute, and every page still works without it.
   ======================================================================================= */
(function () {
  "use strict";

  // 1. Listen: read a block aloud with the browser's own speech engine. Nothing leaves the page.
  document.querySelectorAll("[data-listen]").forEach(function (button) {
    if (!("speechSynthesis" in window)) { button.hidden = true; return; }
    button.addEventListener("click", function () {
      if (window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
        button.textContent = "Listen";
        return;
      }
      var target = document.querySelector(button.dataset.listen);
      if (!target) { return; }
      var utterance = new SpeechSynthesisUtterance(target.innerText);
      utterance.onend = function () { button.textContent = "Listen"; };
      window.speechSynthesis.speak(utterance);
      button.textContent = "Stop";
    });
  });

  // 2. Copy, and optionally open the original message: the read-only reply flow.
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) { return navigator.clipboard.writeText(text); }
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); } finally { document.body.removeChild(area); }
    return Promise.resolve();
  }
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var source = document.querySelector(button.dataset.copy);
      if (!source) { return; }
      var label = button.textContent;
      copyText(source.innerText.trim()).then(function () {
        button.textContent = "Copied";
        window.setTimeout(function () { button.textContent = label; }, 1800);
        if (button.dataset.open) { window.open(button.dataset.open, "_blank", "noopener"); }
      });
    });
  });

  // 3. Keyboard: J/K move, E done, S snooze -- only where the page marks an element data-key.
  document.addEventListener("keydown", function (event) {
    if (event.ctrlKey || event.metaKey || event.altKey) { return; }
    var tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable) { return; }
    var target = document.querySelector('[data-key="' + event.key.toLowerCase() + '"]');
    if (!target) { return; }
    event.preventDefault();
    if (target.tagName === "FORM") {
      if (target.requestSubmit) { target.requestSubmit(); } else { target.submit(); }
    } else {
      target.click();
    }
  });

  // 4. Building screen: replay the stored steps one by one. The server already rendered them as
  //    done, so with JavaScript off -- or reduced motion on -- the page is simply complete.
  var steps = document.querySelector("[data-animate-steps]");
  if (steps && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var items = Array.prototype.slice.call(steps.querySelectorAll("li"));
    var bar = document.querySelector("[data-progress]");
    items.forEach(function (li) { li.classList.remove("is-done"); });
    if (bar) { bar.style.width = "0%"; }
    items.forEach(function (li, index) {
      window.setTimeout(function () {
        li.classList.add("is-done");
        if (bar) { bar.style.width = Math.round(((index + 1) / items.length) * 100) + "%"; }
      }, 450 * (index + 1));
    });
  }

  // 5. Dismissable asides ("Keep reading without Slack").
  document.querySelectorAll("[data-dismiss]").forEach(function (button) {
    button.addEventListener("click", function () {
      var box = button.closest("[data-dismissable]");
      if (box) { box.hidden = true; }
    });
  });
})();
