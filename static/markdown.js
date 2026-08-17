const SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);
const INLINE_MARKERS = new Set(["\\", "`", "!", "[", "<", "*", "_", "~", "\n"]);
const DATASET_CODE_BOUNDARY = /[\p{L}\p{N}_]/u;

export function eurostatDatasetUrl(datasetCode) {
  const code = String(datasetCode || "").trim();
  if (!code) return "";
  return `https://ec.europa.eu/eurostat/databrowser/view/${encodeURIComponent(code)}/default/table?lang=en`;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function leadingSpaces(line) {
  return line.match(/^[ \t]*/)?.[0].replaceAll("\t", "    ").length || 0;
}

function findClosingMarker(source, marker, from) {
  let index = from;
  while (index < source.length) {
    index = source.indexOf(marker, index);
    if (index < 0) return -1;
    if (index === 0 || source[index - 1] !== "\\") return index;
    index += marker.length;
  }
  return -1;
}

function isWordCharacter(value) {
  return Boolean(value && /[\p{L}\p{N}]/u.test(value));
}

function findEmphasisClosing(source, marker, from) {
  let closing = findClosingMarker(source, marker, from);
  while (closing >= 0) {
    if (
      marker !== "_"
      || !isWordCharacter(source[closing - 1])
      || !isWordCharacter(source[closing + 1])
    ) {
      return closing;
    }
    closing = findClosingMarker(source, marker, closing + marker.length);
  }
  return -1;
}

function safeLink(rawUrl) {
  const value = rawUrl.trim().replace(/^<|>$/g, "");
  try {
    const url = new URL(value, window.location.href);
    if (!SAFE_PROTOCOLS.has(url.protocol)) return null;
    return url;
  } catch {
    return null;
  }
}

function appendLink(target, label, rawUrl) {
  const url = safeLink(rawUrl);
  if (!url) {
    target.appendChild(document.createTextNode(label));
    return;
  }
  const link = element("a");
  link.href = url.href;
  appendInline(link, label);
  if (url.protocol === "http:" || url.protocol === "https:") {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  target.appendChild(link);
}

function datasetLink(target, code, url) {
  const link = element("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.appendChild(document.createTextNode(code));
  target.appendChild(link);
}

function datasetCodeAt(source, index, datasetLinks) {
  if (!datasetLinks?.length || DATASET_CODE_BOUNDARY.test(source[index - 1] || "")) return null;
  for (const item of datasetLinks) {
    if (
      source.startsWith(item.code, index)
      && !DATASET_CODE_BOUNDARY.test(source[index + item.code.length] || "")
    ) {
      return item;
    }
  }
  return null;
}

function linkAt(source, index) {
  const image = source.startsWith("![", index);
  const labelStart = index + (image ? 2 : 1);
  const labelEnd = findClosingMarker(source, "]", labelStart);
  if (labelEnd < 0 || source[labelEnd + 1] !== "(") return null;

  let cursor = labelEnd + 2;
  let depth = 1;
  let destination = "";
  while (cursor < source.length) {
    const character = source[cursor];
    if (character === "\\" && cursor + 1 < source.length) {
      destination += source[cursor + 1];
      cursor += 2;
      continue;
    }
    if (character === "(") depth += 1;
    if (character === ")") {
      depth -= 1;
      if (depth === 0) break;
    }
    destination += character;
    cursor += 1;
  }
  if (depth !== 0) return null;

  const destinationMatch = destination.trim().match(/^(?:<([^>]+)>|(\S+?))(?:\s+["'].*["'])?$/);
  if (!destinationMatch) return null;
  return {
    end: cursor + 1,
    image,
    label: source.slice(labelStart, labelEnd),
    url: destinationMatch[1] || destinationMatch[2],
  };
}

function appendInline(target, source, context = {}) {
  let index = 0;
  while (index < source.length) {
    const character = source[index];

    if (character === "\\" && index + 1 < source.length) {
      target.appendChild(document.createTextNode(source[index + 1]));
      index += 2;
      continue;
    }

    if (character === "`") {
      const run = source.slice(index).match(/^`+/)?.[0] || "`";
      const closing = findClosingMarker(source, run, index + run.length);
      if (closing >= 0) {
        const content = source
          .slice(index + run.length, closing)
          .replace(/\s*\n\s*/g, " ")
          .replace(/^ | $/g, "");
        const dataset = context.datasetLinks?.find((item) => item.code === content);
        if (dataset) {
          const link = element("a");
          link.href = dataset.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.appendChild(element("code", "", content));
          target.appendChild(link);
        } else {
          target.appendChild(element("code", "", content));
        }
        index = closing + run.length;
        continue;
      }
    }

    if ((character === "!" && source[index + 1] === "[") || character === "[") {
      const match = linkAt(source, index);
      if (match) {
        if (match.image) {
          appendLink(target, match.label || match.url, match.url);
        } else {
          appendLink(target, match.label, match.url);
        }
        index = match.end;
        continue;
      }
    }

    if (character === "<") {
      const closing = source.indexOf(">", index + 1);
      if (closing >= 0) {
        const candidate = source.slice(index + 1, closing);
        if (/^(?:https?:\/\/|mailto:)/i.test(candidate)) {
          appendLink(target, candidate.replace(/^mailto:/i, ""), candidate);
          index = closing + 1;
          continue;
        }
        if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(candidate)) {
          appendLink(target, candidate, `mailto:${candidate}`);
          index = closing + 1;
          continue;
        }
      }
    }

    if (source.startsWith("**", index) || source.startsWith("__", index)) {
      const marker = source.slice(index, index + 2);
      const closing = findClosingMarker(source, marker, index + 2);
      if (closing > index + 2) {
        const strong = element("strong");
        appendInline(strong, source.slice(index + 2, closing), context);
        target.appendChild(strong);
        index = closing + 2;
        continue;
      }
    }

    if (source.startsWith("~~", index)) {
      const closing = findClosingMarker(source, "~~", index + 2);
      if (closing > index + 2) {
        const deleted = element("del");
        appendInline(deleted, source.slice(index + 2, closing), context);
        target.appendChild(deleted);
        index = closing + 2;
        continue;
      }
    }

    if (character === "*" || character === "_") {
      const isIntrawordUnderscore = (
        character === "_"
        && isWordCharacter(source[index - 1])
        && isWordCharacter(source[index + 1])
      );
      const closing = isIntrawordUnderscore
        ? -1
        : findEmphasisClosing(source, character, index + 1);
      if (closing > index + 1) {
        const emphasis = element("em");
        appendInline(emphasis, source.slice(index + 1, closing), context);
        target.appendChild(emphasis);
        index = closing + 1;
        continue;
      }
    }

    if (character === "\n") {
      const previousTwo = source.slice(Math.max(0, index - 2), index);
      if (previousTwo === "  " || source[index - 1] === "\\") {
        target.appendChild(document.createElement("br"));
      } else {
        target.appendChild(document.createTextNode(" "));
      }
      index += 1;
      continue;
    }

    const dataset = datasetCodeAt(source, index, context.datasetLinks);
    if (dataset) {
      datasetLink(target, dataset.code, dataset.url);
      index += dataset.code.length;
      continue;
    }

    const bareUrl = source.slice(index).match(/^https?:\/\/[^\s<]+/i);
    if (bareUrl) {
      const url = bareUrl[0].replace(/[),.;:!?]+$/, "");
      appendLink(target, url, url);
      index += url.length;
      continue;
    }

    let end = index + 1;
    while (
      end < source.length
      && !INLINE_MARKERS.has(source[end])
      && !source.startsWith("http://", end)
      && !source.startsWith("https://", end)
      && !datasetCodeAt(source, end, context.datasetLinks)
    ) {
      end += 1;
    }
    target.appendChild(document.createTextNode(source.slice(index, end)));
    index = end;
  }
}

function splitTableRow(line) {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  const cells = [];
  let cell = "";
  let codeFence = "";
  for (let index = 0; index < trimmed.length; index += 1) {
    const character = trimmed[index];
    if (character === "\\" && trimmed[index + 1] === "|") {
      cell += "|";
      index += 1;
      continue;
    }
    if (character === "`") {
      const run = trimmed.slice(index).match(/^`+/)?.[0] || "`";
      codeFence = codeFence === run ? "" : codeFence || run;
      cell += run;
      index += run.length - 1;
      continue;
    }
    if (character === "|" && !codeFence) {
      cells.push(cell.trim());
      cell = "";
      continue;
    }
    cell += character;
  }
  cells.push(cell.trim());
  return cells;
}

function isTableDivider(line) {
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function renderTable(lines, start, container, context) {
  const headers = splitTableRow(lines[start]);
  const alignments = splitTableRow(lines[start + 1]).map((cell) => {
    if (cell.startsWith(":") && cell.endsWith(":")) return "center";
    if (cell.endsWith(":")) return "right";
    return "left";
  });
  const table = element("table", "markdown-table");
  const thead = element("thead");
  const headerRow = element("tr");
  headers.forEach((header, index) => {
    const th = element("th");
    th.style.textAlign = alignments[index] || "left";
    appendInline(th, header, context);
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = element("tbody");
  let cursor = start + 2;
  while (cursor < lines.length && lines[cursor].includes("|") && lines[cursor].trim()) {
    const row = element("tr");
    splitTableRow(lines[cursor]).forEach((value, index) => {
      const td = element("td");
      td.style.textAlign = alignments[index] || "left";
      appendInline(td, value, context);
      row.appendChild(td);
    });
    tbody.appendChild(row);
    cursor += 1;
  }
  table.appendChild(tbody);
  const scroll = element("div", "markdown-table-scroll");
  scroll.appendChild(table);
  container.appendChild(scroll);
  return cursor;
}

function listMatch(line) {
  const match = line.match(/^([ \t]*)([-+*]|\d+[.)])\s+(.*)$/);
  if (!match) return null;
  return {
    indent: leadingSpaces(match[1]),
    ordered: /^\d/.test(match[2]),
    start: /^\d/.test(match[2]) ? Number.parseInt(match[2], 10) : 1,
    content: match[3],
  };
}

function renderList(lines, start, container, context) {
  const first = listMatch(lines[start]);
  const root = element(first.ordered ? "ol" : "ul");
  if (first.ordered && first.start !== 1) root.start = first.start;
  container.appendChild(root);
  const stack = [{ indent: first.indent, ordered: first.ordered, list: root, item: null }];
  let cursor = start;

  while (cursor < lines.length) {
    const match = listMatch(lines[cursor]);
    if (!match || match.indent < first.indent) break;

    while (stack.length > 1 && match.indent < stack.at(-1).indent) stack.pop();
    let level = stack.at(-1);
    if (match.indent > level.indent) {
      if (!level.item) break;
      const nested = element(match.ordered ? "ol" : "ul");
      if (match.ordered && match.start !== 1) nested.start = match.start;
      level.item.appendChild(nested);
      level = { indent: match.indent, ordered: match.ordered, list: nested, item: null };
      stack.push(level);
    } else if (match.ordered !== level.ordered) {
      if (stack.length === 1) break;
      stack.pop();
      level = stack.at(-1);
    }

    const item = element("li");
    const task = match.content.match(/^\[([ xX])]\s+(.*)$/);
    if (task) {
      item.className = "task-list-item";
      const checkbox = element("input");
      checkbox.type = "checkbox";
      checkbox.checked = task[1].toLocaleLowerCase() === "x";
      checkbox.disabled = true;
      item.appendChild(checkbox);
      const copy = element("span");
      appendInline(copy, task[2], context);
      item.appendChild(copy);
    } else {
      appendInline(item, match.content, context);
    }
    level.list.appendChild(item);
    level.item = item;
    cursor += 1;
  }
  return cursor;
}

function renderBlocks(container, source, context) {
  const lines = source.split("\n");
  let cursor = 0;
  while (cursor < lines.length) {
    const line = lines[cursor];
    const trimmed = line.trim();
    if (!trimmed) {
      cursor += 1;
      continue;
    }

    const fence = trimmed.match(/^(`{3,}|~{3,})\s*([\w.+-]*)\s*$/);
    if (fence) {
      const code = [];
      cursor += 1;
      while (cursor < lines.length && !lines[cursor].trim().startsWith(fence[1])) {
        code.push(lines[cursor]);
        cursor += 1;
      }
      if (cursor < lines.length) cursor += 1;
      const pre = element("pre");
      const codeNode = element("code", fence[2] ? `language-${fence[2]}` : "", code.join("\n"));
      pre.appendChild(codeNode);
      container.appendChild(pre);
      continue;
    }

    if (/^(?: {4}|\t)/.test(line)) {
      const code = [];
      while (
        cursor < lines.length
        && (/^(?: {4}|\t)/.test(lines[cursor]) || !lines[cursor].trim())
      ) {
        code.push(lines[cursor].replace(/^(?: {4}|\t)/, ""));
        cursor += 1;
      }
      const pre = element("pre");
      pre.appendChild(element("code", "", code.join("\n").replace(/\n+$/, "")));
      container.appendChild(pre);
      continue;
    }

    if (
      cursor + 1 < lines.length
      && trimmed
      && !line.includes("|")
      && /^\s*(=+|-+)\s*$/.test(lines[cursor + 1])
    ) {
      const node = element(lines[cursor + 1].includes("=") ? "h1" : "h2");
      appendInline(node, trimmed, context);
      container.appendChild(node);
      cursor += 2;
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+?)\s*#*$/);
    if (heading) {
      const node = element(`h${heading[1].length}`);
      appendInline(node, heading[2], context);
      container.appendChild(node);
      cursor += 1;
      continue;
    }

    if (/^(?: {0,3})([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      container.appendChild(element("hr"));
      cursor += 1;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quoted = [];
      while (cursor < lines.length && /^\s*>/.test(lines[cursor])) {
        quoted.push(lines[cursor].replace(/^\s*>\s?/, ""));
        cursor += 1;
      }
      const blockquote = element("blockquote");
      renderBlocks(blockquote, quoted.join("\n"), context);
      container.appendChild(blockquote);
      continue;
    }

    if (
      cursor + 1 < lines.length
      && line.includes("|")
      && isTableDivider(lines[cursor + 1])
    ) {
      cursor = renderTable(lines, cursor, container, context);
      continue;
    }

    if (listMatch(line)) {
      cursor = renderList(lines, cursor, container, context);
      continue;
    }

    const paragraph = [line.trimStart()];
    cursor += 1;
    while (cursor < lines.length && lines[cursor].trim()) {
      const next = lines[cursor];
      const nextTrimmed = next.trim();
      if (
        /^#{1,6}\s+/.test(nextTrimmed)
        || /^(`{3,}|~{3,})/.test(nextTrimmed)
        || /^\s*>/.test(next)
        || listMatch(next)
        || /^(?: {0,3})([-*_])(?:\s*\1){2,}\s*$/.test(next)
        || (
          cursor + 1 < lines.length
          && next.includes("|")
          && isTableDivider(lines[cursor + 1])
        )
      ) {
        break;
      }
      paragraph.push(next.trimStart());
      cursor += 1;
    }
    const node = element("p");
    appendInline(node, paragraph.join("\n"), context);
    container.appendChild(node);
  }
}

export function normalizeMarkdown(value) {
  let source = String(value ?? "").replace(/\r\n?/g, "\n").trim();
  const wrapped = source.match(
    /^(`{3,}|~{3,})\s*(?:markdown|md|commonmark|gfm)\s*\n([\s\S]*?)\n\1\s*$/i,
  );
  if (wrapped) {
    source = wrapped[2].trim();
  } else {
    const genericWrapper = source.match(/^(`{3,}|~{3,})\s*\n([\s\S]*?)\n\1\s*$/);
    if (
      genericWrapper
      && /^(?:#{1,6}\s|[-+*]\s|\d+[.)]\s|>\s|\|.+\|)/m.test(genericWrapper[2])
    ) {
      source = genericWrapper[2].trim();
    }
  }
  return source;
}

export function renderMarkdown(container, value, options = {}) {
  container.replaceChildren();
  const source = normalizeMarkdown(value);
  if (!source) return;
  const datasetLinks = [...new Set(options.datasetCodes || [])]
    .map((code) => String(code || "").trim())
    .filter(Boolean)
    .sort((left, right) => right.length - left.length)
    .map((code) => ({ code, url: eurostatDatasetUrl(code) }));
  renderBlocks(container, source, { datasetLinks });
}

export const markdownTestUtils = {
  datasetCodeAt,
  isTableDivider,
  splitTableRow,
};
