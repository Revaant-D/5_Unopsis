// /search/ — loading feedback and the "/" shortcut (templates/unopsis/app/search.html).
// Plain progressive enhancement: the page works the same with JavaScript off.
(function () {
  "use strict";
  var form = document.querySelector("[data-search-form]");
  if (!form) return;
  var input = form.querySelector("input[name=q]");
  var submit = form.querySelector("[data-search-submit]");
  var askBox = form.querySelector("[data-search-ask]");
  var busy = form.querySelector("[data-search-busy]");

  function showBusy(asking) {
    if (submit) {
      submit.disabled = true;
      submit.textContent = "Searching…";
    }
    if (busy) {
      busy.textContent = asking
        ? "Searching, then writing an answer… this can take a little while."
        : "Searching…";
      busy.hidden = false;
    }
  }

  form.addEventListener("submit", function (event) {
    if (!input.value.trim()) {
      event.preventDefault();       // the server would say the same; save the round trip
      input.focus();
      return;
    }
    showBusy(askBox && askBox.checked);
  });

  // Example chips are plain links; carry the "Also answer" choice along and show progress.
  form.querySelectorAll("[data-search-example]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      input.value = link.textContent.trim();
      showBusy(askBox && askBox.checked);
      form.submit();
    });
  });

  // "/" focuses the search box, unless the user is already typing somewhere.
  document.addEventListener("keydown", function (event) {
    var tag = (event.target.tagName || "").toLowerCase();
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    if (tag === "input" || tag === "textarea" || event.target.isContentEditable) return;
    event.preventDefault();
    input.focus();
    input.select();
  });

  // Browsers restore the page from the back/forward cache with the button still disabled.
  window.addEventListener("pageshow", function () {
    if (submit) {
      submit.disabled = false;
      submit.textContent = "Search";
    }
    if (busy) busy.hidden = true;
  });
})();
