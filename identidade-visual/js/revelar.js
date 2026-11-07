/**
 * Kalman · entrada ao rolar (par do .k-revelar em css/base.css).
 * Marca data-visivel em cada .k-revelar quando ele entra na tela, uma única vez.
 *
 *   <script src="identidade-visual/js/revelar.js" defer></script>   liga sozinho ao carregar
 *   window.kRevelar(elemento)                                      para conteúdo inserido depois
 *
 * Em React: um useEffect com o mesmo IntersectionObserver (ver README).
 */
(function () {
  function revelar(raiz) {
    var alvos = (raiz || document).querySelectorAll(".k-revelar:not([data-visivel])");
    if (!("IntersectionObserver" in window)) {
      alvos.forEach(function (el) { el.setAttribute("data-visivel", ""); });
      return;
    }
    var io = new IntersectionObserver(
      function (entradas) {
        entradas.forEach(function (e) {
          if (e.isIntersecting) {
            e.target.setAttribute("data-visivel", "");
            io.unobserve(e.target);
          }
        });
      },
      { rootMargin: "0px 0px -12% 0px" }
    );
    alvos.forEach(function (el) { io.observe(el); });
  }
  window.kRevelar = revelar;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { revelar(); });
  else revelar();
})();
