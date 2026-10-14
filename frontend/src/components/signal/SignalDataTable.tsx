"use client";

import React, { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";

import { cx } from "@/components/ui/utils";
import type { SignalTableColumn } from "@/components/signal/SignalTable";

export type SignalDataTableColumn<T> = SignalTableColumn<T> & {
  /** Enables header-click sorting; `sortValue` supplies the compared value. */
  sortable?: boolean;
  sortValue?: (row: T) => string | number;
};

export type SignalDataTableProps<T> = {
  columns: SignalDataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  emptyLabel?: string;
  /** Enables the `.dt-search` box; `searchText` defines the searched haystack. */
  searchPlaceholder?: string;
  searchText?: (row: T) => string;
  /** Extra controls rendered inside `.dt-tools` (filters, actions). */
  tools?: React.ReactNode;
  pageSize?: number;
  metaLabel?: string;
  /** Replaces `.dt-foot` entirely - for server-paginated datasets. */
  footer?: React.ReactNode;
  className?: string;
  /**
   * signal-MVP's `selectable: true`: a leading checkbox column plus a header
   * checkbox that is indeterminate on a partial selection. Selection is owned
   * by the caller, because the actions it drives (the approved "Delete
   * selected") live outside the table.
   */
  selectable?: boolean;
  selectedKeys?: Array<string | number>;
  onSelectionChange?: (keys: Array<string | number>) => void;
  selectAllLabel?: string;
  selectRowLabel?: string;
};

const ALIGN_CLASS: Record<"left" | "right" | "center", string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

/**
 * Pager windowing: first, last, current with one neighbour each side, and a
 * `.pp-gap` ellipsis standing in for each elided run (signal.css `.pager`).
 */
const pageItems = (current: number, count: number): (number | "gap")[] => {
  const wanted = new Set<number>([0, count - 1, current - 1, current, current + 1]);
  const pages = [...wanted].filter((p) => p >= 0 && p < count).sort((a, b) => a - b);
  const items: (number | "gap")[] = [];
  for (let i = 0; i < pages.length; i++) {
    if (i > 0 && pages[i] - pages[i - 1] > 1) items.push("gap");
    items.push(pages[i]);
  }
  return items;
};

/**
 * Matches signal-MVP's `.dtable` contract (signal.css `.dtable`, `.dt-tools`,
 * `.dt-search`, `.dt-meta`, `.dt-scroll`, `.dt-foot`, `.dt-empty`, `.pager`):
 * a panel-framed table with a tools row, sticky mono headers, 340px scroll
 * region and a footer pager. Companion to `SignalTable`, which stays the
 * plain `.wtable` primitive.
 */
export default function SignalDataTable<T>({
  columns,
  rows,
  rowKey,
  emptyLabel = "Nothing to show yet.",
  searchPlaceholder = "Search",
  searchText,
  tools,
  pageSize = 10,
  metaLabel,
  footer,
  className,
  selectable = false,
  selectedKeys,
  onSelectionChange,
  selectAllLabel = "Select all rows",
  selectRowLabel = "Select row",
}: SignalDataTableProps<T>) {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !searchText) return rows;
    return rows.filter((row) => searchText(row).toLowerCase().includes(q));
  }, [rows, query, searchText]);

  // Not memoized: callers rebuild `columns` every render, so a useMemo keyed on
  // the column would never hit anyway. Callers wanting cached sort should memo
  // their columns array and this can be revisited.
  const sortCol = sortKey ? columns.find((c) => c.key === sortKey) : undefined;
  let sorted = filtered;
  if (sortCol?.sortValue) {
    const sortValue = sortCol.sortValue;
    const dir = sortDir === "asc" ? 1 : -1;
    sorted = [...filtered].sort((a, b) => {
      const av = sortValue(a);
      const bv = sortValue(b);
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = sorted.slice(safePage * pageSize, safePage * pageSize + pageSize);

  const onSort = (col: SignalDataTableColumn<T>) => {
    if (!col.sortable || !col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col.key);
      setSortDir("asc");
    }
    setPage(0);
  };

  const showTools = Boolean(searchText) || Boolean(tools) || Boolean(metaLabel);

  const selected = new Set(selectedKeys ?? []);
  // Select-all spans the filtered set, not the visible page, matching the
  // mockup: the header checkbox there selects every row the current filter
  // leaves, which is also what the bulk action then operates on.
  const selectableKeys = sorted.map((row) => rowKey(row));
  const selectedCount = selectableKeys.filter((key) => selected.has(key)).length;
  const allSelected = selectableKeys.length > 0 && selectedCount === selectableKeys.length;
  const columnCount = columns.length + (selectable ? 1 : 0);

  const toggleRow = (key: string | number, checked: boolean) => {
    if (!onSelectionChange) return;
    const next = new Set(selected);
    if (checked) next.add(key);
    else next.delete(key);
    onSelectionChange([...next]);
  };

  const toggleAll = (checked: boolean) => {
    if (!onSelectionChange) return;
    const next = new Set(selected);
    for (const key of selectableKeys) {
      if (checked) next.add(key);
      else next.delete(key);
    }
    onSelectionChange([...next]);
  };

  return (
    <div
      className={cx(
        "flex flex-col overflow-hidden rounded-(--r-md) border border-(--line) bg-(--panel)",
        className
      )}
    >
      {showTools ? (
        <div className="flex items-center gap-2.5 border-b border-(--line) px-3.5 py-2.5">
          {searchText ? (
            <div className="input-shell flex h-8 max-w-[250px] flex-1 items-center gap-[7px] rounded-(--r-sm) border border-(--line) bg-(--paper) px-2.5 focus-within:border-[#c9cef7] focus-within:bg-(--panel) focus-within:shadow-[0_0_0_3px_var(--ring)]">
              <Search size={14} className="shrink-0 text-(--t-3)" />
              <input
                type="text"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(0);
                }}
                placeholder={searchPlaceholder}
                aria-label={searchPlaceholder}
                className="w-full border-none bg-transparent text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3)"
              />
            </div>
          ) : null}
          {tools}
          <span className="ms-auto font-(family-name:--mono) text-[11px] text-(--t-3)">
            {metaLabel ?? `${filtered.length} items`}
          </span>
        </div>
      ) : null}

      <div className="max-h-[340px] overflow-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              {selectable ? (
                <th className="sticky top-0 z-[2] w-[34px] border-b border-(--line) bg-(--panel) px-3.5 py-2.5 text-start">
                  <input
                    type="checkbox"
                    aria-label={selectAllLabel}
                    checked={allSelected}
                    ref={(node) => {
                      if (node) node.indeterminate = selectedCount > 0 && !allSelected;
                    }}
                    onChange={(event) => toggleAll(event.target.checked)}
                    className="h-[15px] w-[15px] cursor-pointer accent-(--purple)"
                  />
                </th>
              ) : null}
              {columns.map((col) => {
                const sortable = Boolean(col.sortable && col.sortValue);
                const active = sortKey === col.key;
                return (
                  <th
                    key={col.key}
                    aria-sort={
                      active ? (sortDir === "asc" ? "ascending" : "descending") : undefined
                    }
                    className={cx(
                      "sticky top-0 z-[2] whitespace-nowrap border-b border-(--line) bg-(--panel) px-3.5 py-2.5 text-start font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)",
                      ALIGN_CLASS[col.align ?? "left"]
                    )}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={() => onSort(col)}
                        className="inline-flex cursor-pointer select-none items-center border-none bg-transparent p-0 font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-inherit hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
                      >
                        {col.header}
                        {active ? (
                          <span className="ms-1 text-(--purple)" aria-hidden="true">
                            {sortDir === "asc" ? "▲" : "▼"}
                          </span>
                        ) : null}
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr>
                <td
                  colSpan={columnCount}
                  className="px-4 py-[34px] text-center text-[13px] text-(--t-3)"
                >
                  {emptyLabel}
                </td>
              </tr>
            ) : (
              pageRows.map((row) => (
                <tr key={rowKey(row)} className="transition-colors hover:bg-(--paper)">
                  {selectable ? (
                    <td className="border-b border-(--line-2) px-3.5 py-[11px] align-middle">
                      <input
                        type="checkbox"
                        aria-label={selectRowLabel}
                        checked={selected.has(rowKey(row))}
                        onChange={(event) => toggleRow(rowKey(row), event.target.checked)}
                        className="h-[15px] w-[15px] cursor-pointer accent-(--purple)"
                      />
                    </td>
                  ) : null}
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cx(
                        "border-b border-(--line-2) px-3.5 py-[11px] align-middle text-[13px] text-(--t-1)",
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
      </div>

      {footer ? (
        <div className="flex items-center gap-3 border-t border-(--line) px-3.5 py-[9px] text-[12px] text-(--t-3)">
          {footer}
        </div>
      ) : pageCount > 1 ? (
        <div className="flex items-center gap-3 border-t border-(--line) px-3.5 py-[9px] text-[12px] text-(--t-3)">
          <nav className="inline-flex items-center gap-1" aria-label="Pagination">
            <button
              type="button"
              disabled={safePage === 0}
              onClick={() => setPage(safePage - 1)}
              aria-label="Previous page"
              className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-[13px] font-medium text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
            >
              <ChevronLeft size={14} />
            </button>
            {pageItems(safePage, pageCount).map((item, idx) =>
              item === "gap" ? (
                <span key={`gap-${idx}`} aria-hidden="true" className="px-[3px] text-(--t-3)">
                  …
                </span>
              ) : (
                <button
                  key={item}
                  type="button"
                  onClick={() => setPage(item)}
                  aria-current={item === safePage ? "page" : undefined}
                  className={cx(
                    "h-8 min-w-8 rounded-(--r-sm) px-2 text-[13px] font-medium",
                    item === safePage
                      ? "bg-(--ink) text-white"
                      : "text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1)"
                  )}
                >
                  {item + 1}
                </button>
              )
            )}
            <button
              type="button"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage(safePage + 1)}
              aria-label="Next page"
              className="inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-[13px] font-medium text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40"
            >
              <ChevronRight size={14} />
            </button>
          </nav>
          <span className="ms-auto font-(family-name:--mono) text-[11px] text-(--t-3)">
            {safePage * pageSize + 1}-{Math.min((safePage + 1) * pageSize, sorted.length)} of{" "}
            {sorted.length}
          </span>
        </div>
      ) : null}
    </div>
  );
}
