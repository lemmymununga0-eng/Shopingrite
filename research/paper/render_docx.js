// Renders content.json (written by build.py) to a Word document that follows the journal's instructions:
// A4, 1-inch margins, Times New Roman 10 pt, single spacing, 14 pt bold title, consecutive page numbers,
// corresponding-author block at the lower left of the first page.  Usage: node render_docx.js content.json out.docx
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, BorderStyle, AlignmentType, ImageRun, Footer,
  PageNumber, LevelFormat, VerticalAlign, TabStopType,
} = require("docx");

const [, , inFile, outFile] = process.argv;
const content = JSON.parse(fs.readFileSync(inFile, "utf8"));
const FONT = "Times New Roman";
const BODY = 20;            // half-points: 10 pt
const SMALL = 17;           // 8.5 pt (tables)
const TEXT_WIDTH = 9026;    // A4 width 11906 minus 2 x 1440 margins, in DXA

// ---------- numbering of tables and figures (order of appearance) ----------
const numbers = { T: {}, F: {} };
let tN = 0, fN = 0;
for (const b of content.blocks) {
  if (b.t === "table") numbers.T[b.key] = ++tN;
  if (b.t === "figure") numbers.F[b.key] = ++fN;
}
function refs(s) {
  return s.replace(/\{([TF]):([A-Za-z0-9_]+)\}/g, (m, k, key) => {
    const n = numbers[k][key];
    if (!n) throw new Error(`unknown reference ${m}`);
    return (k === "T" ? "Table " : "Figure ") + n;
  });
}

// ---------- inline markup: *italic* ; a literal asterisk is written \* ----------
function runs(text, opts = {}) {
  const t = refs(text).replace(/\\\*/g, "\u0001");
  const parts = t.split("*");
  return parts.map((p, i) => new TextRun({
    text: p.replace(/\u0001/g, "*"), italics: (i % 2 === 1) || opts.italics, bold: opts.bold, font: FONT, size: opts.size || BODY,
  })).filter((r, i) => parts[i] !== "");
}

const para = (text, o = {}) => new Paragraph({
  children: runs(text, o), alignment: o.align || AlignmentType.JUSTIFIED, keepNext: o.keepNext,
  spacing: { before: o.before ?? 0, after: o.after ?? 100, line: 240 }, indent: o.indent, keepLines: o.keepLines,
});

// ---------- lists ----------
const numberingConfigs = [{
  reference: "bullets",
  levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }],
}];
let listCount = 0;

// ---------- tables ----------
const thin = { style: BorderStyle.SINGLE, size: 6, color: "000000" };
const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };

function table(b) {
  const total = b.widths.reduce((a, c) => a + c, 0);
  const cols = b.widths.map(w => Math.round(w / total * TEXT_WIDTH));
  cols[cols.length - 1] += TEXT_WIDTH - cols.reduce((a, c) => a + c, 0);
  // Short tables are kept on one page. Long ones may break between rows (the header row repeats), but the header stays with the first row.
  const short = b.rows.length <= 7;
  const cell = (txt, ci, header, last, o = {}) => new TableCell({
    width: { size: cols[ci], type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
    margins: { top: 40, bottom: 40, left: 70, right: 70 },
    borders: { top: header ? thin : none, bottom: header || last ? thin : none, left: none, right: none },
    children: [new Paragraph({
      children: runs(String(txt), { size: b.size || SMALL, bold: header || o.bold }), keepNext: header || (short ? !last : (o.first === true || o.penultimate === true)),
      alignment: ci === 0 || (b.leftAll) ? AlignmentType.LEFT : (b.align && b.align[ci]) || AlignmentType.CENTER,
      spacing: { before: 0, after: 0, line: 240 },
    })],
  });
  const rows = [new TableRow({ tableHeader: true, cantSplit: true, children: b.header.map((h, i) => cell(h, i, true, false)) })];
  b.rows.forEach((r, ri) => {
    const last = ri === b.rows.length - 1;
    const bold = Array.isArray(b.boldRows) && b.boldRows.includes(ri);
    rows.push(new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, i, false, last, { bold, first: ri === 0, penultimate: ri === b.rows.length - 2 })) }));
  });
  const out = [
    new Paragraph({ children: [new TextRun({ text: `Table ${numbers.T[b.key]}. `, bold: true, font: FONT, size: BODY }), ...runs(b.caption)],
                    keepNext: true, spacing: { before: 160, after: 60, line: 240 }, alignment: AlignmentType.LEFT }),
    new Table({ width: { size: TEXT_WIDTH, type: WidthType.DXA }, columnWidths: cols, rows }),
  ];
  if (b.note) out.push(new Paragraph({ children: runs(b.note, { size: 16, italics: false }), spacing: { before: 40, after: 160, line: 240 }, alignment: AlignmentType.LEFT }));
  else out.push(new Paragraph({ children: [], spacing: { before: 0, after: 120 } }));
  return out;
}

// ---------- figures ----------
function figure(b) {
  const buf = fs.readFileSync(b.path);
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  const wpx = Math.round(b.widthIn * 96), hpx = Math.round(wpx * h / w);
  return [
    new Paragraph({ children: [new ImageRun({ type: "png", data: buf, transformation: { width: wpx, height: hpx },
                    altText: { title: `Figure ${numbers.F[b.key]}`, description: b.alt || b.caption, name: b.key } })],
                    alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 40 } }),
    new Paragraph({ children: [new TextRun({ text: `Figure ${numbers.F[b.key]}. `, bold: true, font: FONT, size: BODY }), ...runs(b.caption)],
                    alignment: AlignmentType.JUSTIFIED, spacing: { before: 0, after: 160, line: 240 } }),
  ];
}

// ---------- body ----------
const children = [];
for (const b of content.blocks) {
  switch (b.t) {
    case "title":
      children.push(new Paragraph({ children: [new TextRun({ text: refs(b.text), bold: true, font: FONT, size: 28 })], alignment: AlignmentType.CENTER, spacing: { before: 0, after: 160, line: 240 } }));
      break;
    case "authors":
      b.lines.forEach((l, i) => children.push(para(l, { align: AlignmentType.CENTER, after: i === b.lines.length - 1 ? 160 : 20, bold: i === 0 })));
      break;
    case "h1": children.push(para(b.text, { bold: true, align: AlignmentType.LEFT, before: 200, after: 80, keepNext: true })); break;
    case "h2": children.push(para(b.text, { bold: true, align: AlignmentType.LEFT, before: 120, after: 60, keepNext: true })); break;
    case "h3": children.push(para(b.text, { bold: true, italics: true, align: AlignmentType.LEFT, before: 80, after: 40, keepNext: true })); break;
    case "abstract":
      children.push(para("Abstract", { bold: true, align: AlignmentType.LEFT, before: 60, after: 60, keepNext: true }));
      children.push(para(b.text));
      break;
    case "keywords":
      children.push(new Paragraph({ children: [new TextRun({ text: "Keywords: ", bold: true, font: FONT, size: BODY }), ...runs(b.text)], spacing: { before: 40, after: 160, line: 240 }, alignment: AlignmentType.LEFT }));
      break;
    case "p": children.push(para(b.text, { align: b.align === "left" ? AlignmentType.LEFT : AlignmentType.JUSTIFIED })); break;
    case "bullets":
      b.items.forEach(it => children.push(new Paragraph({ children: runs(it), numbering: { reference: "bullets", level: 0 }, alignment: AlignmentType.LEFT, spacing: { before: 0, after: 50, line: 240 } })));
      children.push(new Paragraph({ children: [], spacing: { before: 0, after: 40 } }));
      break;
    case "numbered": {
      const ref = `num${++listCount}`;
      numberingConfigs.push({ reference: ref, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] });
      b.items.forEach(it => children.push(new Paragraph({ children: runs(it), numbering: { reference: ref, level: 0 }, alignment: AlignmentType.LEFT, spacing: { before: 0, after: 50, line: 240 } })));
      children.push(new Paragraph({ children: [], spacing: { before: 0, after: 40 } }));
      break;
    }
    case "table": children.push(...table(b)); break;
    case "figure": children.push(...figure(b)); break;
    case "refs":
      b.items.forEach(it => children.push(new Paragraph({ children: runs(it), alignment: AlignmentType.LEFT, indent: { left: 540, hanging: 540 }, spacing: { before: 0, after: 70, line: 240 } })));
      break;
    case "pagebreak": children.push(new Paragraph({ children: [], pageBreakBefore: true })); break;
    default: throw new Error("unknown block " + b.t);
  }
}

// ---------- footers: first page carries the corresponding-author block at the lower left ----------
const pageNo = () => new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: BODY })] });
const firstFooter = new Footer({ children: [
  new Paragraph({ border: { top: { style: BorderStyle.SINGLE, size: 4, color: "000000", space: 4 } }, spacing: { before: 0, after: 20 }, children: [] }),
  ...content.meta.corresponding.map(l => new Paragraph({ alignment: AlignmentType.LEFT, spacing: { before: 0, after: 10, line: 240 }, children: runs(l, { size: 17 }) })),
  pageNo(),
] });
const defaultFooter = new Footer({ children: [pageNo()] });

const doc = new Document({
  creator: content.meta.creator, title: content.meta.docTitle, description: content.meta.description,
  styles: { default: { document: { run: { font: FONT, size: BODY, language: { value: "en-GB" } } } } },
  numbering: { config: numberingConfigs },
  sections: [{
    properties: { titlePage: true, page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: defaultFooter, first: firstFooter },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outFile, buf);
  console.log(`wrote ${outFile} (${(buf.length / 1024).toFixed(0)} KB); tables ${tN}, figures ${fN}`);
});
