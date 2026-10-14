"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Command as CommandIcon, FileText, Play, Search, X } from "lucide-react";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "./command";
import type { TabId } from "@/types/auditWorkspace";
import { tabs } from "@/types/auditWorkspace";

export type PaletteAction = {
  id: string;
  label: string;
  icon: React.ReactNode;
  shortcut?: string;
  onSelect: () => void;
};

type CommandPaletteProps = {
  setActiveTab: (tab: TabId) => void;
  onRunAudit?: () => void;
  onExportPdf?: () => void;
  onExportJson?: () => void;
};

export default function CommandPalette({
  setActiveTab,
  onRunAudit,
  onExportPdf,
  onExportJson,
}: CommandPaletteProps) {
  const [open, setOpen] = useState(false);

  const actions: PaletteAction[] = useMemo(() => {
    const items: PaletteAction[] = [];

    tabs.forEach((tab, i) => {
      items.push({
        id: `tab-${tab.id}`,
        label: `Go to ${tab.label}`,
        icon: <Search className="h-4 w-4" />,
        shortcut: `Alt+${i + 1}`,
        onSelect: () => {
          setActiveTab(tab.id);
          setOpen(false);
        },
      });
    });

    if (onRunAudit) {
      items.push({
        id: "run-audit",
        label: "Run New Assessment",
        icon: <Play className="h-4 w-4" />,
        onSelect: () => {
          onRunAudit();
          setOpen(false);
        },
      });
    }
    if (onExportPdf) {
      items.push({
        id: "export-pdf",
        label: "Export PDF Report",
        icon: <FileText className="h-4 w-4" />,
        onSelect: () => {
          onExportPdf();
          setOpen(false);
        },
      });
    }
    if (onExportJson) {
      items.push({
        id: "export-json",
        label: "Export JSON",
        icon: <FileText className="h-4 w-4" />,
        onSelect: () => {
          onExportJson();
          setOpen(false);
        },
      });
    }

    return items;
  }, [setActiveTab, onRunAudit, onExportPdf, onExportJson]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
      onClick={() => setOpen(false)}
    >
      <div className="backdrop-surface absolute inset-0" />

      <Command
        label="Command palette"
        filter={(value, search) => (value.toLowerCase().includes(search.toLowerCase()) ? 1 : 0)}
        className="surface-card-strong relative w-full max-w-lg overflow-hidden rounded-2xl animate-in fade-in zoom-in-95 duration-150"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-(--border) px-4 py-3">
          <CommandIcon className="h-4 w-4 text-(--muted-foreground)" />
          <CommandInput autoFocus placeholder="Type a command" />
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-md p-1 text-(--muted-foreground) transition-colors hover:bg-(--surface-subtle) hover:text-(--foreground)"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <CommandList>
          <CommandEmpty>No matching commands</CommandEmpty>
          {actions.map((action) => (
            <CommandItem key={action.id} value={action.label} onSelect={action.onSelect}>
              <span className="text-(--muted-foreground)">{action.icon}</span>
              <span className="flex-1">{action.label}</span>
              {action.shortcut && (
                <kbd className="rounded border border-(--border) bg-(--background) px-1.5 py-0.5 font-mono text-[10px] text-(--muted-foreground)">
                  {action.shortcut}
                </kbd>
              )}
            </CommandItem>
          ))}
        </CommandList>

        <div className="flex items-center justify-between border-t border-(--border) px-4 py-2 text-[10px] text-(--muted-foreground)">
          <span>↑↓ navigate · ↵ select · esc close</span>
          <kbd className="rounded border border-(--border) bg-(--background) px-1.5 py-0.5 font-mono">
            ⌘K
          </kbd>
        </div>
      </Command>
    </div>
  );
}
