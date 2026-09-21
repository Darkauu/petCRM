// JS plano, sin framework. Solo lo que el HTML no puede hacer solo.

// Precio unico vs. precio por tamano en el formulario de servicio.
document.querySelectorAll("[data-price-mode]").forEach(function (radio) {
  radio.addEventListener("change", function () {
    document.querySelectorAll("[data-price-block]").forEach(function (block) {
      block.hidden = block.dataset.priceBlock !== radio.value;
    });
  });
});

// Confirmacion antes de archivar. El formulario funciona igual sin JS:
// esto solo agrega la pregunta.
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

// Evita el doble envio cuando la conexion va lenta y el dueno vuelve a tocar.
document.querySelectorAll("form.form").forEach(function (form) {
  form.addEventListener("submit", function () {
    window.setTimeout(function () {
      form.querySelectorAll("button[type=submit]").forEach(function (btn) {
        btn.disabled = true;
      });
    }, 0);
  });
});

// Total en vivo de la visita. Si el JS no corre, el servidor igual suma
// bien: esto solo evita que el duenio tenga que sumar de cabeza.
(function () {
  var out = document.querySelector("[data-total]");
  if (!out) return;

  function recalc() {
    var cents = 0;
    document.querySelectorAll(".line").forEach(function (line) {
      var check = line.querySelector(".line-check");
      var amount = line.querySelector("[data-amount]");
      if (!check || !check.checked || !amount) return;
      var value = parseFloat((amount.value || "").replace(",", "."));
      if (!isNaN(value) && value >= 0) cents += Math.round(value * 100);
    });
    out.textContent = "$" + (cents / 100).toFixed(2);
  }

  document.addEventListener("change", recalc);
  document.addEventListener("input", recalc);
  recalc();
})();
