/*
 * Draws every Vega-Lite chart on the page.
 *
 * Markup:  <div data-vega-spec="/vega-lite/chart1.json"></div>
 *
 * The spec is fetched from its own endpoint (the same file that is submitted and that opens in
 * the Vega-Lite editor), and Vega-Lite then loads the chart's numbers itself through the spec's
 * "data": {"url": ...} -- no data is ever written into the page.
 *
 * The one change made here is width "container": the spec file uses a fixed width so it renders
 * the same in the editor and as a PNG, while on a page the chart should fill its column.
 * Needs vega, vega-lite and vega-embed loaded first.
 */
document.querySelectorAll("[data-vega-spec]").forEach(function (element) {
  fetch(element.dataset.vegaSpec)
    .then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }
      return response.json();
    })
    .then(function (spec) {
      spec.width = "container";
      return vegaEmbed(element, spec, {actions: {export: true, source: true, compiled: false, editor: true}});
    })
    .catch(function (error) {
      // A chart that fails to load should say so, not leave an empty box with no explanation.
      element.textContent = "Chart failed to load: " + error.message;
    });
});
