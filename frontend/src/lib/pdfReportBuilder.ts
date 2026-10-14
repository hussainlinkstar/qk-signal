/**
 * PdfReportBuilder, programmatic multi-page PDF report generator using jsPDF.
 *
 * Provides a fluent API for building structured reports with cover pages,
 * tables of contents, score cards, data tables, bar charts, and automatic
 * page-break management with consistent headers/footers.
 */

import jsPDF from "jspdf";
import type { ReportBranding } from "./reportBranding";
import { hexToRgb } from "./reportBranding";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_WIDTH = 210; // A4 mm
const PAGE_HEIGHT = 297;
const MARGIN_LEFT = 18;
const MARGIN_RIGHT = 18;
const MARGIN_TOP = 20;
const MARGIN_BOTTOM = 25;
const CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT;
const SAFE_Y = PAGE_HEIGHT - MARGIN_BOTTOM;
const FONT_FAMILY = "helvetica";

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

export type TocEntry = { title: string; page: number };

export class PdfReportBuilder {
  readonly pdf: jsPDF;
  private readonly branding: ReportBranding;
  private cursorY = MARGIN_TOP;
  private toc: TocEntry[] = [];

  constructor(branding: ReportBranding) {
    this.branding = branding;
    this.pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
    this.pdf.setFont(FONT_FAMILY);
  }

  // -----------------------------------------------------------------------
  // Cursor / Page helpers
  // -----------------------------------------------------------------------

  get y(): number {
    return this.cursorY;
  }

  get pageNumber(): number {
    return this.pdf.getNumberOfPages();
  }

  advance(mm: number): void {
    this.cursorY += mm;
    if (this.cursorY > SAFE_Y) this.newPage();
  }

  ensureSpace(mm: number): void {
    if (this.cursorY + mm > SAFE_Y) this.newPage();
  }

  newPage(): void {
    this.pdf.addPage();
    this.cursorY = MARGIN_TOP;
  }

  // -----------------------------------------------------------------------
  // Cover Page
  // -----------------------------------------------------------------------

  addCoverPage(opts: { url: string; date: Date; reportTitle: string }): void {
    const [pr, pg, pb] = hexToRgb(this.branding.primaryColor);

    // Background gradient band
    this.pdf.setFillColor(pr, pg, pb);
    this.pdf.rect(0, 0, PAGE_WIDTH, 110, "F");

    // White overlay triangle for visual flair
    this.pdf.setFillColor(255, 255, 255);
    this.pdf.triangle(0, 110, PAGE_WIDTH, 85, PAGE_WIDTH, 110, "F");

    // Logo / company name
    let logoY = 30;
    if (this.branding.logoBase64) {
      try {
        this.pdf.addImage(this.branding.logoBase64, "PNG", MARGIN_LEFT, logoY, 40, 40);
        logoY += 48;
      } catch {
        // Fallback to text if image fails
        this.pdf.setFontSize(28);
        this.pdf.setTextColor(255, 255, 255);
        this.pdf.setFont(FONT_FAMILY, "bold");
        this.pdf.text(this.branding.companyName, MARGIN_LEFT, logoY + 10);
        logoY += 20;
      }
    } else {
      this.pdf.setFontSize(28);
      this.pdf.setTextColor(255, 255, 255);
      this.pdf.setFont(FONT_FAMILY, "bold");
      this.pdf.text(this.branding.companyName, MARGIN_LEFT, logoY + 10);
      logoY += 20;
    }

    // Report title
    this.pdf.setFontSize(24);
    this.pdf.setTextColor(255, 255, 255);
    this.pdf.setFont(FONT_FAMILY, "bold");
    this.pdf.text(opts.reportTitle, MARGIN_LEFT, logoY + 5);

    // URL and date below the gradient band
    this.pdf.setFontSize(13);
    this.pdf.setTextColor(60, 60, 60);
    this.pdf.setFont(FONT_FAMILY, "normal");
    this.pdf.text(opts.url, MARGIN_LEFT, 130);

    this.pdf.setFontSize(11);
    this.pdf.setTextColor(120, 120, 120);
    this.pdf.text(
      `Generated: ${opts.date.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })}`,
      MARGIN_LEFT,
      140
    );

    // Footer on cover
    this.pdf.setFontSize(8);
    this.pdf.setTextColor(160, 160, 160);
    this.pdf.text(this.branding.footerText, PAGE_WIDTH / 2, PAGE_HEIGHT - 12, { align: "center" });

    this.newPage();
  }

  // -----------------------------------------------------------------------
  // Table of Contents
  // -----------------------------------------------------------------------

  /** Call AFTER all sections have been added to resolve page numbers */
  insertTableOfContents(tocPageIndex: number): void {
    // Insert a page at position tocPageIndex (0-indexed)
    // jsPDF doesn't support page insertion natively, so we record TOC entries
    // and write them on the pre-allocated TOC page
    const currentPage = this.pdf.getNumberOfPages();
    this.pdf.setPage(tocPageIndex);

    const [pr, pg, pb] = hexToRgb(this.branding.primaryColor);

    this.pdf.setFontSize(20);
    this.pdf.setTextColor(pr, pg, pb);
    this.pdf.setFont(FONT_FAMILY, "bold");
    this.pdf.text("Table of Contents", MARGIN_LEFT, MARGIN_TOP + 5);

    let tocY = MARGIN_TOP + 20;
    this.pdf.setFontSize(12);
    this.pdf.setFont(FONT_FAMILY, "normal");

    for (const entry of this.toc) {
      this.pdf.setTextColor(40, 40, 40);
      this.pdf.text(entry.title, MARGIN_LEFT + 4, tocY);

      // Dotted leader
      const titleWidth = this.pdf.getTextWidth(entry.title) + MARGIN_LEFT + 6;
      const pageStr = String(entry.page);
      const pageX = PAGE_WIDTH - MARGIN_RIGHT;
      this.pdf.setTextColor(120, 120, 120);
      this.pdf.text(pageStr, pageX, tocY, { align: "right" });

      // Dots
      const dotsStart = titleWidth;
      const dotsEnd = pageX - this.pdf.getTextWidth(pageStr) - 4;
      if (dotsEnd > dotsStart) {
        const dotStr = " . ".repeat(
          Math.floor((dotsEnd - dotsStart) / this.pdf.getTextWidth(" . "))
        );
        this.pdf.setTextColor(180, 180, 180);
        this.pdf.text(dotStr, dotsStart, tocY);
      }

      tocY += 8;
    }

    // Restore to last page
    this.pdf.setPage(currentPage);
  }

  registerTocEntry(title: string): void {
    this.toc.push({ title, page: this.pageNumber });
  }

  // -----------------------------------------------------------------------
  // Section Header
  // -----------------------------------------------------------------------

  addSectionHeader(title: string, opts?: { registerToc?: boolean }): void {
    this.ensureSpace(20);

    const [pr, pg, pb] = hexToRgb(this.branding.primaryColor);

    // Colored bar
    this.pdf.setFillColor(pr, pg, pb);
    this.pdf.rect(MARGIN_LEFT, this.cursorY, 4, 10, "F");

    this.pdf.setFontSize(18);
    this.pdf.setTextColor(pr, pg, pb);
    this.pdf.setFont(FONT_FAMILY, "bold");
    this.pdf.text(title, MARGIN_LEFT + 8, this.cursorY + 8);

    if (opts?.registerToc !== false) {
      this.registerTocEntry(title);
    }

    this.cursorY += 16;
  }

  addSubHeader(title: string): void {
    this.ensureSpace(12);
    const [sr, sg, sb] = hexToRgb(this.branding.secondaryColor);
    this.pdf.setFontSize(13);
    this.pdf.setTextColor(sr, sg, sb);
    this.pdf.setFont(FONT_FAMILY, "bold");
    this.pdf.text(title, MARGIN_LEFT, this.cursorY + 5);
    this.cursorY += 10;
  }

  // -----------------------------------------------------------------------
  // Text
  // -----------------------------------------------------------------------

  addParagraph(text: string, opts?: { fontSize?: number; color?: string; bold?: boolean }): void {
    const fontSize = opts?.fontSize ?? 10;
    const color = opts?.color ?? "#333333";
    const [r, g, b] = hexToRgb(color);

    this.pdf.setFontSize(fontSize);
    this.pdf.setTextColor(r, g, b);
    this.pdf.setFont(FONT_FAMILY, opts?.bold ? "bold" : "normal");

    const lines = this.pdf.splitTextToSize(text, CONTENT_WIDTH);
    const lineHeight = fontSize * 0.45;

    for (const line of lines) {
      this.ensureSpace(lineHeight + 1);
      this.pdf.text(line, MARGIN_LEFT, this.cursorY);
      this.cursorY += lineHeight;
    }
    this.cursorY += 3;
  }

  addBulletList(items: string[], opts?: { fontSize?: number }): void {
    const fontSize = opts?.fontSize ?? 10;
    this.pdf.setFontSize(fontSize);
    this.pdf.setFont(FONT_FAMILY, "normal");
    this.pdf.setTextColor(50, 50, 50);

    const lineHeight = fontSize * 0.45;
    const bulletIndent = MARGIN_LEFT + 4;
    const textIndent = MARGIN_LEFT + 8;
    const maxWidth = CONTENT_WIDTH - 8;

    for (const item of items) {
      const lines = this.pdf.splitTextToSize(item, maxWidth);
      const blockHeight = lines.length * lineHeight + 2;
      this.ensureSpace(blockHeight);

      // Bullet dot
      const [ar, ag, ab] = hexToRgb(this.branding.accentColor);
      this.pdf.setFillColor(ar, ag, ab);
      this.pdf.circle(bulletIndent, this.cursorY - 1.2, 1, "F");

      this.pdf.setTextColor(50, 50, 50);
      for (const line of lines) {
        this.pdf.text(line, textIndent, this.cursorY);
        this.cursorY += lineHeight;
      }
      this.cursorY += 1.5;
    }
    this.cursorY += 2;
  }

  // -----------------------------------------------------------------------
  // Score Card (inline colored box with score)
  // -----------------------------------------------------------------------

  addScoreCard(label: string, score: number, maxScore = 100): void {
    this.ensureSpace(18);

    const pct = Math.min(score / maxScore, 1);
    const color = pct >= 0.7 ? this.branding.accentColor : pct >= 0.4 ? "#F59E0B" : "#EF4444";
    const [cr, cg, cb] = hexToRgb(color);

    // Background
    this.pdf.setFillColor(245, 245, 250);
    this.pdf.roundedRect(MARGIN_LEFT, this.cursorY, CONTENT_WIDTH, 14, 2, 2, "F");

    // Score bar
    const barWidth = Math.max(pct * (CONTENT_WIDTH - 4), 2);
    this.pdf.setFillColor(cr, cg, cb);
    this.pdf.roundedRect(MARGIN_LEFT + 2, this.cursorY + 9, barWidth, 3, 1.5, 1.5, "F");

    // Label
    this.pdf.setFontSize(11);
    this.pdf.setTextColor(40, 40, 40);
    this.pdf.setFont(FONT_FAMILY, "bold");
    this.pdf.text(label, MARGIN_LEFT + 4, this.cursorY + 7);

    // Score value
    this.pdf.setFontSize(14);
    this.pdf.setTextColor(cr, cg, cb);
    this.pdf.text(`${Math.round(score)}`, PAGE_WIDTH - MARGIN_RIGHT - 4, this.cursorY + 7.5, {
      align: "right",
    });

    this.cursorY += 18;
  }

  // -----------------------------------------------------------------------
  // Data Table
  // -----------------------------------------------------------------------

  addTable(headers: string[], rows: string[][]): void {
    const colCount = headers.length;
    const colWidth = CONTENT_WIDTH / colCount;
    const rowHeight = 7;

    // Header row
    this.ensureSpace(rowHeight + 2);
    const [sr, sg, sb] = hexToRgb(this.branding.secondaryColor);
    this.pdf.setFillColor(sr, sg, sb);
    this.pdf.rect(MARGIN_LEFT, this.cursorY, CONTENT_WIDTH, rowHeight, "F");

    this.pdf.setFontSize(9);
    this.pdf.setTextColor(255, 255, 255);
    this.pdf.setFont(FONT_FAMILY, "bold");
    headers.forEach((header, i) => {
      this.pdf.text(header, MARGIN_LEFT + i * colWidth + 2, this.cursorY + 5);
    });
    this.cursorY += rowHeight;

    // Data rows
    this.pdf.setFont(FONT_FAMILY, "normal");
    rows.forEach((row, rowIndex) => {
      this.ensureSpace(rowHeight + 1);

      // Alternating background
      if (rowIndex % 2 === 0) {
        this.pdf.setFillColor(248, 248, 252);
        this.pdf.rect(MARGIN_LEFT, this.cursorY, CONTENT_WIDTH, rowHeight, "F");
      }

      this.pdf.setTextColor(50, 50, 50);
      this.pdf.setFontSize(9);
      row.forEach((cell, i) => {
        const truncated = cell.length > 40 ? cell.slice(0, 37) + "..." : cell;
        this.pdf.text(truncated, MARGIN_LEFT + i * colWidth + 2, this.cursorY + 5);
      });
      this.cursorY += rowHeight;
    });

    this.cursorY += 4;
  }

  // -----------------------------------------------------------------------
  // Bar Chart (drawn with rect primitives)
  // -----------------------------------------------------------------------

  addBarChart(title: string, data: { label: string; value: number }[], maxValue = 100): void {
    const chartHeight = Math.min(data.length * 12 + 20, 80);
    this.ensureSpace(chartHeight + 10);

    // Title
    this.pdf.setFontSize(11);
    this.pdf.setTextColor(60, 60, 60);
    this.pdf.setFont(FONT_FAMILY, "bold");
    this.pdf.text(title, MARGIN_LEFT, this.cursorY + 4);
    this.cursorY += 10;

    const barMaxWidth = CONTENT_WIDTH - 40;
    const barHeight = 7;
    const gap = 4;

    for (const item of data) {
      this.ensureSpace(barHeight + gap + 2);

      // Label
      this.pdf.setFontSize(8);
      this.pdf.setTextColor(80, 80, 80);
      this.pdf.setFont(FONT_FAMILY, "normal");
      this.pdf.text(item.label, MARGIN_LEFT, this.cursorY + 5);

      // Bar background
      const barX = MARGIN_LEFT + 38;
      this.pdf.setFillColor(230, 230, 240);
      this.pdf.roundedRect(barX, this.cursorY, barMaxWidth, barHeight, 1.5, 1.5, "F");

      // Bar fill
      const pct = Math.min(item.value / maxValue, 1);
      const fillWidth = Math.max(pct * barMaxWidth, 2);
      const color = pct >= 0.7 ? this.branding.accentColor : pct >= 0.4 ? "#F59E0B" : "#EF4444";
      const [cr, cg, cb] = hexToRgb(color);
      this.pdf.setFillColor(cr, cg, cb);
      this.pdf.roundedRect(barX, this.cursorY, fillWidth, barHeight, 1.5, 1.5, "F");

      // Value label
      this.pdf.setFontSize(8);
      this.pdf.setTextColor(cr, cg, cb);
      this.pdf.setFont(FONT_FAMILY, "bold");
      this.pdf.text(`${Math.round(item.value)}`, barX + fillWidth + 3, this.cursorY + 5);

      this.cursorY += barHeight + gap;
    }
    this.cursorY += 4;
  }

  // -----------------------------------------------------------------------
  // Divider
  // -----------------------------------------------------------------------

  addDivider(): void {
    this.ensureSpace(6);
    this.pdf.setDrawColor(220, 220, 230);
    this.pdf.setLineWidth(0.3);
    this.pdf.line(MARGIN_LEFT, this.cursorY, PAGE_WIDTH - MARGIN_RIGHT, this.cursorY);
    this.cursorY += 6;
  }

  // -----------------------------------------------------------------------
  // Page Footer + Numbers (call at the very end)
  // -----------------------------------------------------------------------

  addPageFooters(): void {
    const totalPages = this.pdf.getNumberOfPages();
    for (let i = 1; i <= totalPages; i++) {
      this.pdf.setPage(i);

      // Footer text
      this.pdf.setFontSize(7);
      this.pdf.setTextColor(160, 160, 160);
      this.pdf.setFont(FONT_FAMILY, "normal");
      this.pdf.text(this.branding.footerText, PAGE_WIDTH / 2, PAGE_HEIGHT - 10, {
        align: "center",
      });

      // Page number (skip cover)
      if (i > 1) {
        this.pdf.setFontSize(8);
        this.pdf.setTextColor(140, 140, 140);
        this.pdf.text(`${i} / ${totalPages}`, PAGE_WIDTH - MARGIN_RIGHT, PAGE_HEIGHT - 10, {
          align: "right",
        });
      }
    }
  }

  // -----------------------------------------------------------------------
  // Save
  // -----------------------------------------------------------------------

  save(fileName: string): void {
    this.pdf.save(fileName);
  }
}
