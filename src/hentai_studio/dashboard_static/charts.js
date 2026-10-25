import { $ } from "./dom.js";

const svgNS = "http://www.w3.org/2000/svg";

export function chartGeometry(points = [], width = 760, height = 240, pad = 16) {
  const valid = points.filter(point => Number.isFinite(point.step) && Number.isFinite(point.loss));
  if (valid.length < 2) return {line: "", area: "", validation: "", markers: []};
  const losses = valid.flatMap(point => [point.loss, point.evalLoss].filter(Number.isFinite));
  const low = Math.min(...losses), high = Math.max(...losses);
  const first = Math.min(...valid.map(point => point.step));
  const last = Math.max(...valid.map(point => point.step));
  const x = point => pad + (point.step - first) / Math.max(1, last - first) * (width - 2 * pad);
  const y = value => pad + (high - value) / Math.max(0.001, high - low) * (height - 2 * pad);
  const coordinates = valid.map(point => [x(point), y(point.loss)]);
  const markers = valid.filter(point => Number.isFinite(point.evalLoss)).map(point => [x(point), y(point.evalLoss)]);
  const path = values => values.map(([a, b], index) => `${index ? "L" : "M"}${a.toFixed(1)},${b.toFixed(1)}`).join(" ");
  const line = path(coordinates);
  return {
    line,
    area: `${line} L${coordinates.at(-1)[0]},${height} L${coordinates[0][0]},${height} Z`,
    validation: path(markers),
    markers,
  };
}

export function drawChartInto(svgId, points) {
  const svg = $(svgId);
  const geometry = chartGeometry(points);
  const grid = svg.querySelector(".grid-lines");
  if (!grid.childElementCount) {
    for (const fraction of [0.2, 0.4, 0.6, 0.8]) {
      const line = document.createElementNS(svgNS, "line");
      for (const [key, value] of Object.entries({x1: 0, x2: 760, y1: 240 * fraction, y2: 240 * fraction})) {
        line.setAttribute(key, value);
      }
      grid.append(line);
    }
  }
  svg.querySelector(".line").setAttribute("d", geometry.line);
  svg.querySelector(".area").setAttribute("d", geometry.area);
  svg.querySelector(".eval-line")?.setAttribute("d", geometry.validation);
  const markers = svg.querySelector(".eval-points");
  if (markers) {
    markers.replaceChildren(...geometry.markers.map(([x, y]) => {
      const circle = document.createElementNS(svgNS, "circle");
      circle.setAttribute("cx", x);
      circle.setAttribute("cy", y);
      circle.setAttribute("r", 4);
      return circle;
    }));
  }
}
