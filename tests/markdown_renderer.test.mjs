import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../static/markdown.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { markdownTestUtils, normalizeMarkdown } = await import(moduleUrl);

test("unwraps a model response fenced as Markdown", () => {
  const source = "```markdown\n## Finding\n\nPopulation **increased**.\n```";
  assert.equal(normalizeMarkdown(source), "## Finding\n\nPopulation **increased**.");
});

test("does not unwrap ordinary code blocks", () => {
  const source = "```python\nprint('hello')\n```";
  assert.equal(normalizeMarkdown(source), source);
});

test("unwraps an unlabeled fence only when it contains a Markdown document", () => {
  assert.equal(
    normalizeMarkdown("```\n# Finding\n\n- Germany\n- France\n```"),
    "# Finding\n\n- Germany\n- France",
  );
  assert.equal(normalizeMarkdown("```\nconst value = 42;\n```"), "```\nconst value = 42;\n```");
});

test("parses escaped pipes and code spans in GFM tables", () => {
  assert.deepEqual(
    markdownTestUtils.splitTableRow("| Dataset | Meaning \\| caveat | `geo|time` |"),
    ["Dataset", "Meaning | caveat", "`geo|time`"],
  );
});

test("recognizes valid table dividers only", () => {
  assert.equal(markdownTestUtils.isTableDivider("| :--- | ---: |"), true);
  assert.equal(markdownTestUtils.isTableDivider("| --- | no |"), false);
});
