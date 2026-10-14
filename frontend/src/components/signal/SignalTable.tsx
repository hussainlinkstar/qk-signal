"use client";

import { cx } from "@/components/ui/utils";

export type SignalTableColumn<T> = {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  renderCell: (row: T) => React.ReactNode;
};

export type SignalTableProps<T> = {
  columns: SignalTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  emptyLabel?: string;
  className?: string;
};

const ALIGN_CLASS: Record<"left" | "right" | "center", string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

/**
 * Matches signal-MVP's `.wtable`/`.wtable th`/`.wtable td` pattern (see
 * /Users/user/signal-MVP/signal.css lines 278-282).
 */
export default function SignalTable<T>({
  columns,
  rows,
  rowKey,
  emptyLabel = "Nothing to show yet.",
  className,
}: SignalTableProps<T>) {
  return (
    <table className={cx("w-full border-collapse", className)}>
      <thead>
        <tr>
          {columns.map((col) => (
            <th
              key={col.key}
              className={cx(
                "border-b border-(--line) px-4 py-[11px] font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)",
                ALIGN_CLASS[col.align ?? "left"]
              )}
            >
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="[&>tr:last-child>td]:border-b-0">
        {rows.length === 0 ? (
          <tr>
            <td
              colSpan={columns.length}
              className="px-4 py-[26px] text-center text-[13px] text-(--t-3)"
            >
              {emptyLabel}
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cx(
                    "border-b border-(--line-2) px-4 py-[13px] align-middle text-[13px] text-(--t-1)",
                    ALIGN_CLASS[col.align ?? "left"]
                  )}
                >
                  {col.renderCell(row)}
                </td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
