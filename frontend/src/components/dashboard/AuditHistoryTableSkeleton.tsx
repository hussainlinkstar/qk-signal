import React from "react";

export const AuditHistoryTableSkeleton = () => {
  // Render 5 placeholder rows
  const rows = Array.from({ length: 5 }, (_, i) => i);

  return (
    <table className="w-full text-sm">
      <thead className="sticky top-0 z-10 border-b border-(--line) bg-[color-mix(in_srgb,var(--panel)_90%,transparent)] ">
        <tr className="text-left text-xs uppercase tracking-wider text-(--t-2)">
          <th className="px-4 py-3 w-10"></th>
          <th className="px-3 py-3">URL</th>
          <th className="px-3 py-3 text-center">SEO</th>
          <th className="px-3 py-3 text-center">AI visibility</th>
          <th className="px-3 py-3 text-center">AI answers</th>
          <th className="px-3 py-3 text-center">Status</th>
          <th className="px-3 py-3 text-right">Date</th>
          <th className="px-4 py-3 text-right">Actions</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((rowIdx) => (
          <tr key={rowIdx} className="border-b border-surface-border/60">
            {/* Checkbox col */}
            <td className="px-4 py-4">
              <div className="h-4 w-4 rounded bg-(--line-2) animate-pulse" />
            </td>
            {/* URL col */}
            <td className="px-3 py-4">
              <div className="h-4 w-3/4 max-w-[200px] rounded bg-(--line-2) animate-pulse" />
            </td>
            {/* SEO */}
            <td className="px-3 py-4 text-center">
              <div className="mx-auto h-5 w-8 rounded-full bg-(--line-2) animate-pulse" />
            </td>
            {/* GEO */}
            <td className="px-3 py-4 text-center">
              <div className="mx-auto h-5 w-8 rounded-full bg-(--line-2) animate-pulse" />
            </td>
            {/* AEO */}
            <td className="px-3 py-4 text-center">
              <div className="mx-auto h-5 w-8 rounded-full bg-(--line-2) animate-pulse" />
            </td>
            {/* Status */}
            <td className="px-3 py-4 text-center">
              <div className="mx-auto h-5 w-16 rounded-full bg-(--line-2) animate-pulse" />
            </td>
            {/* Date */}
            <td className="px-3 py-4">
              <div className="ml-auto h-4 w-20 rounded bg-(--line-2) animate-pulse" />
            </td>
            {/* Actions */}
            <td className="px-4 py-4">
              <div className="ml-auto flex items-center justify-end gap-2">
                <div className="h-8 w-14 rounded-md bg-(--line-2) animate-pulse" />
                <div className="h-8 w-24 rounded-md bg-(--line-2) animate-pulse" />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};
