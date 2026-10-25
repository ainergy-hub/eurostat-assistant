// Spreadsheet apps evaluate cells starting with these characters as formulas.
const FORMULA_PREFIX = /^[=+\-@\t\r]/;

export function csvCell(value) {
  let text = value === null || value === undefined ? "" : String(value);
  // A leading apostrophe makes Excel and LibreOffice show the value as text. Numbers are left
  // alone so negative values stay numeric.
  if (typeof value === "string" && FORMULA_PREFIX.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function csvText(rows, columns) {
  return [
    columns.map((column) => csvCell(column.label)).join(","),
    ...rows.map((row) => columns.map((column) => csvCell(row[column.key])).join(",")),
  ].join("\n");
}
