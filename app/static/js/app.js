// JS plano, sin framework. Solo lo que el HTML no puede hacer solo, y
// siempre como mejora: si el JS no carga, todo lo de abajo sigue
// funcionando por el camino normal del formulario.


// ---- Confirmacion propia de la aplicacion -----------------------------
// window.confirm lo dibuja el navegador: se ve distinto en cada uno, no
// se puede traducir ni estilar, y no existe fuera de un navegador. Este
// dialogo es DOM de la aplicacion, asi que se muda tal cual el dia que
// esto viva dentro de una app.
var petConfirm = (function () {
  var dialog = document.getElementById("confirm-dialog");

  return function ask(message, okLabel) {
    // Navegador sin <dialog>: se cae al del sistema. Feo, pero nunca
    // deja pasar una accion destructiva sin preguntar.
    if (!dialog || typeof dialog.showModal !== "function") {
      return Promise.resolve(window.confirm(message));
    }

    dialog.querySelector("[data-confirm-text]").textContent = message;
    dialog.querySelector("[data-confirm-accept]").textContent =
      okLabel || "Confirmar";

    return new Promise(function (resolve) {
      function done() {
        dialog.removeEventListener("close", done);
        resolve(dialog.returnValue === "ok");
      }
      dialog.addEventListener("close", done);
      dialog.returnValue = "";        // Escape cierra sin confirmar
      dialog.showModal();
    });
  };
})();

document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    if (form.dataset.confirmed === "1") return;   // ya se pregunto
    event.preventDefault();
    petConfirm(form.dataset.confirm, form.dataset.confirmOk)
      .then(function (ok) {
        if (!ok) return;
        form.dataset.confirmed = "1";
        // requestSubmit vuelve a lanzar el evento, que esta vez pasa de
        // largo: asi el resto de los manejadores siguen corriendo.
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
      });
  });
});


// ---- Buscador con resultados mientras se escribe ----------------------
// El formulario y su boton siguen ahi: esto solo evita el viaje al
// servidor cuando hay JS.
(function () {
  var box = document.querySelector("[data-search-url]");
  if (!box || !window.fetch) return;

  var input = box.querySelector("input[type=search]");
  var list = box.querySelector("[data-results]");
  var url = box.dataset.searchUrl;
  var timer = null;
  var controller = null;
  var active = -1;

  function hide() {
    list.hidden = true;
    list.innerHTML = "";
    active = -1;
    input.setAttribute("aria-expanded", "false");
  }

  function render(rows) {
    if (!rows.length) { hide(); return; }
    list.innerHTML = "";
    rows.forEach(function (row) {
      var name = document.createElement("span");
      name.className = "list-title";
      name.textContent = row.name;          // textContent, nunca innerHTML:
      var sub = document.createElement("span");  // el nombre lo escribio
      sub.className = "list-sub";                // una persona.
      sub.textContent = row.sub;

      var link = document.createElement("a");
      link.href = row.url;
      link.appendChild(name);
      link.appendChild(sub);

      var item = document.createElement("li");
      item.appendChild(link);
      list.appendChild(item);
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    active = -1;
  }

  function search() {
    var term = input.value.trim();
    if (!term) { hide(); return; }

    // Cancela la peticion anterior: al escribir rapido llegan varias y
    // la ultima en responder no siempre es la ultima que se pidio.
    if (controller) controller.abort();
    controller = ("AbortController" in window) ? new AbortController() : null;

    // La URL puede venir ya con parametros (destino=visita), asi que
    // el separador se decide, no se asume.
    var sep = (url.indexOf("?") === -1) ? "?" : "&";
    fetch(url + sep + "q=" + encodeURIComponent(term),
          controller ? { signal: controller.signal } : undefined)
      .then(function (res) { return res.ok ? res.json() : { rows: [] }; })
      .then(function (data) { render(data.rows || []); })
      .catch(function () { /* cancelada o sin red: se deja como estaba */ });
  }

  function highlight(items) {
    items.forEach(function (item, i) {
      item.classList.toggle("on", i === active);
    });
    if (active >= 0) items[active].scrollIntoView({ block: "nearest" });
  }

  input.addEventListener("input", function () {
    window.clearTimeout(timer);
    timer = window.setTimeout(search, 180);
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Escape") { hide(); return; }

    var items = Array.prototype.slice.call(list.querySelectorAll("a"));
    if (!items.length || list.hidden) return;

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      active += (event.key === "ArrowDown") ? 1 : -1;
      if (active < 0) active = items.length - 1;
      if (active >= items.length) active = 0;
      highlight(items);
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();       // sin seleccion, Enter busca normal
      items[active].click();
    }
  });

  // Cerrar al tocar fuera. Se escucha el clic y no el blur, porque el
  // blur se dispara antes de que el toque llegue al resultado.
  document.addEventListener("click", function (event) {
    if (!box.contains(event.target)) hide();
  });
})();


// ---- Dia y noche ------------------------------------------------------
// La eleccion se guarda en el navegador y la aplica el script en linea
// de la cabecera, antes de pintar. Si no se ha elegido nada, manda la
// preferencia del sistema.
(function () {
  var boton = document.querySelector("[data-tema]");
  if (!boton) return;

  boton.addEventListener("click", function () {
    var raiz = document.documentElement;
    var actual = raiz.dataset.theme;
    if (!actual) {
      actual = (window.matchMedia &&
                window.matchMedia("(prefers-color-scheme: dark)").matches)
        ? "dark" : "light";
    }
    var nuevo = (actual === "dark") ? "light" : "dark";
    raiz.dataset.theme = nuevo;
    try {
      localStorage.setItem("tema", nuevo);
    } catch (e) { /* navegacion privada: vale para esta pestania */ }
  });
})();


// ---- Precio unico vs. precio por tamano en el formulario de servicio --
document.querySelectorAll("[data-price-mode]").forEach(function (radio) {
  radio.addEventListener("change", function () {
    document.querySelectorAll("[data-price-block]").forEach(function (block) {
      block.hidden = block.dataset.priceBlock !== radio.value;
    });
  });
});


// ---- Total en vivo de la visita ---------------------------------------
// Si el JS no corre, el servidor igual suma bien: esto solo evita que el
// duenio tenga que sumar de cabeza.
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


// ---- Evita el doble envio cuando la conexion va lenta -----------------
document.querySelectorAll("form.form").forEach(function (form) {
  form.addEventListener("submit", function () {
    window.setTimeout(function () {
      form.querySelectorAll("button[type=submit]").forEach(function (btn) {
        btn.disabled = true;
      });
    }, 0);
  });
});
