/**
 * Table style tokens, consistent styling for all data tables.
 *
 * Usage:
 *   import { TABLE } from "@/components/ui/tableTokens";
 *   <thead className={TABLE.head}>
 *     <tr className={TABLE.headerRow}>
 *       <th className={TABLE.headerCell}>...</th>
 *     </tr>
 *   </thead>
 *   <tbody>
 *     <tr className={TABLE.bodyRow}>
 *       <td className={TABLE.bodyCell}>...</td>
 *     </tr>
 *   </tbody>
 */

/** Sticky thead wrapper */
export const TABLE_HEAD_CLASS = "glass-surface sticky top-0 z-sticky border-none";

/** Header row with border */
export const TABLE_HEADER_ROW_CLASS =
  "border-b border-(--border) text-left text-xs uppercase tracking-wider text-(--text-muted)";

/** Individual header cell */
export const TABLE_HEADER_CELL_CLASS = "px-3 py-2";

/** Body row with border + hover */
export const TABLE_BODY_ROW_CLASS =
  "border-b border-(--border) text-(--foreground) transition-colors hover:bg-(--surface-subtle)";

/** Body cell */
export const TABLE_BODY_CELL_CLASS = "px-3 py-2";

export const TABLE = {
  head: TABLE_HEAD_CLASS,
  headerRow: TABLE_HEADER_ROW_CLASS,
  headerCell: TABLE_HEADER_CELL_CLASS,
  bodyRow: TABLE_BODY_ROW_CLASS,
  bodyCell: TABLE_BODY_CELL_CLASS,
} as const;
