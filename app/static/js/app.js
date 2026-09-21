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
