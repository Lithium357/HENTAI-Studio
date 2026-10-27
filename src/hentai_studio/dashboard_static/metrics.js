export function metricGeometry(rows, key, width = 600, height = 150) {
  const values = rows.map((row, index) => ({
    x: Number.isFinite(row.step) ? row.step : index,
    y: row[key]
  })).filter(p => Number.isFinite(p.y));
  if (!values.length) return {
    path: "",
    summary: "No metrics yet."
  };
  const xs = values.map(p => p.x),
    ys = values.map(p => p.y);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  const path = values.map((p, i) => `${i ? "L" : "M"}${(10 + (p.x-minX)/(maxX-minX || 1)*(width-20)).toFixed(1)},${(height-10-(p.y-minY)/(maxY-minY || 1)*(height-20)).toFixed(1)}`).join(" ");
  return {
    path,
    summary: `${key}: ${ys.at(-1).toPrecision(5)} · ${values.length} points · range ${minY.toPrecision(4)}–${maxY.toPrecision(4)}`
  };
}
