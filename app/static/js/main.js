(function () {
  "use strict";

  // PayFast hand-off page: submit automatically (the button is the no-JS fallback)
  var auto = document.querySelector("form[data-autosubmit]");
  if (auto) setTimeout(function () { auto.submit(); }, 400);

  // Product page: show only the sizes for the chosen colour and tint the placeholder drawing
  var buy = document.getElementById("buy");
  if (buy) {
    var colors = buy.querySelectorAll('input[name="color"]');
    var groups = buy.querySelectorAll(".sizes-pick");
    var img = document.getElementById("pdp-img");
    var label = document.getElementById("color-name");

    function showColor(name, hex) {
      groups.forEach(function (g) {
        var match = g.dataset.color === name;
        g.hidden = !match;
        if (!match) g.querySelectorAll("input").forEach(function (i) { i.checked = false; });
      });
      if (label) label.textContent = name;
      if (img && img.dataset.ph && hex) img.src = img.dataset.ph.replace("__HEX__", hex);
    }

    if (colors.length) {
      var first = buy.querySelector('input[name="color"]:checked') || colors[0];
      showColor(first.value, first.dataset.hex);
      colors.forEach(function (c) {
        c.addEventListener("change", function () { showColor(c.value, c.dataset.hex); });
      });
    }
    buy.addEventListener("submit", function (e) {
      if (!buy.querySelector('input[name="variant_id"]:checked')) {
        e.preventDefault();
        alert("Choose a size first.");
      }
    });
  }
// PDP gallery thumbnails
var mainImg = document.getElementById("pdp-img");
var thumbBtns = document.querySelectorAll(".thumb-btn");
if (mainImg && thumbBtns.length) {
  thumbBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      mainImg.src = btn.dataset.src;
      mainImg.removeAttribute("data-ph"); // disable colour-tint override
      thumbBtns.forEach(function (b) { b.classList.remove("is-active"); });
      btn.classList.add("is-active");
    });
  });
}
  // Admin product form: add / remove variant rows
  var rows = document.getElementById("variant-rows");
  var tpl = document.getElementById("variant-template");
  var add = document.querySelector("[data-add-variant]");
  if (rows && tpl && add) {
    add.addEventListener("click", function () {
      rows.appendChild(tpl.content.cloneNode(true));
    });
    rows.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-remove-row]");
      if (btn) btn.closest("tr").remove();
    });
  }
})();
