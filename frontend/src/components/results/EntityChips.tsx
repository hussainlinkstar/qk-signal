"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Building2, CircleHelp, Landmark, MapPin, Package, Tag, User } from "lucide-react";

export type EntityChipItem = {
  name: string;
  type?: string;
  confidence?: number | null;
};

type EntityChipsProps = {
  entities: EntityChipItem[];
  suggestions?: EntityChipItem[];
  onEdit?: (nextEntity: EntityChipItem, previousEntity: EntityChipItem) => void;
  onRemove?: (entity: EntityChipItem) => void;
  onAdd?: (entity: EntityChipItem) => void;
};

const normalizeEntityType = (value?: string) => {
  const type = String(value ?? "Entity")
    .trim()
    .toLowerCase();
  if (type === "person") return "Person";
  if (type === "organization" || type === "org") return "Organization";
  if (type === "location" || type === "place") return "Location";
  if (type === "product") return "Product";
  if (type === "event") return "Event";
  return value?.trim() || "Entity";
};

const iconByType = {
  Person: User,
  Organization: Building2,
  Location: MapPin,
  Product: Package,
  Event: Landmark,
  Entity: Tag,
} as const;

const EntityChips = ({ entities, suggestions = [], onEdit, onRemove, onAdd }: EntityChipsProps) => {
  const { t } = useTranslation();
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");

  const normalizedSuggestions = useMemo(() => {
    const existing = new Set(entities.map((entity) => entity.name.trim().toLowerCase()));
    const unique = new Map<string, EntityChipItem>();

    suggestions.forEach((entry) => {
      const name = entry.name?.trim();
      if (!name) return;
      const key = name.toLowerCase();
      if (existing.has(key) || unique.has(key)) return;
      unique.set(key, { ...entry, name, type: normalizeEntityType(entry.type) });
    });

    return Array.from(unique.values());
  }, [entities, suggestions]);

  const beginEdit = (entity: EntityChipItem, index: number) => {
    setEditingIndex(index);
    setDraftName(entity.name);
  };

  const cancelEdit = () => {
    setEditingIndex(null);
    setDraftName("");
  };

  const confirmEdit = (entity: EntityChipItem, index: number) => {
    const nextName = draftName.trim();
    if (!nextName) {
      cancelEdit();
      return;
    }

    if (nextName !== entity.name && onEdit) {
      onEdit({ ...entity, name: nextName }, entity);
    }

    if (editingIndex === index) {
      cancelEdit();
    }
  };

  return (
    <div className="p-6 bg-(--panel) rounded-[14px] border-0 bg-[#EEF1F6]">
      <h3 className="text-xl font-semibold text-(--t-1) mb-3">
        {t("signalAuditReport.entities.chipsTitle")}
      </h3>
      {entities.length === 0 ? (
        <p className="text-(--t-2)">{t("signalAuditReport.entities.chipsEmpty")}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {entities.map((entity, index) => {
            const type = normalizeEntityType(entity.type);
            const Icon = iconByType[type as keyof typeof iconByType] ?? CircleHelp;
            const confidence =
              typeof entity.confidence === "number" && Number.isFinite(entity.confidence)
                ? `${Math.round(entity.confidence)}%`
                : null;

            return (
              <div
                key={`${entity.name}-${index}`}
                className="inline-flex items-center gap-2 rounded-full border-0 bg-white px-3 py-1.5 text-xs text-(--t-1)"
              >
                <Icon className="h-3.5 w-3.5 text-thoth-brass" aria-hidden="true" />
                {editingIndex === index ? (
                  <>
                    <input
                      value={draftName}
                      onChange={(event) => setDraftName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          confirmEdit(entity, index);
                        }
                        if (event.key === "Escape") {
                          event.preventDefault();
                          cancelEdit();
                        }
                      }}
                      className="w-28 bg-transparent text-xs text-(--t-1) focus:outline-hidden"
                      autoFocus
                    />
                    <button
                      type="button"
                      onClick={() => confirmEdit(entity, index)}
                      className="text-emerald-300 hover:text-emerald-200"
                      aria-label={`Confirm edit for ${entity.name}`}
                    >
                      ✓
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="text-(--t-2) hover:text-(--t-1)"
                      aria-label={`Cancel edit for ${entity.name}`}
                    >
                      ✕
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="text-left text-(--t-1) hover:text-(--t-1)"
                      onClick={() => beginEdit(entity, index)}
                      aria-label={`Edit ${entity.name}`}
                    >
                      {entity.name}
                    </button>
                    {type !== "Entity" ? <span className="text-(--t-2)">{type}</span> : null}
                    {confidence && <span className="text-(--t-3)">{confidence}</span>}
                    {onRemove && (
                      <button
                        type="button"
                        className="text-(--t-2) hover:text-(--t-1)"
                        onClick={() => onRemove(entity)}
                        aria-label={`Remove ${entity.name}`}
                      >
                        ×
                      </button>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}

      {normalizedSuggestions.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs uppercase tracking-wide text-(--t-3)">Suggestions</p>
          <div className="flex flex-wrap gap-2">
            {normalizedSuggestions.map((entity) => (
              <button
                key={`${entity.name}-${entity.type}`}
                type="button"
                onClick={() => onAdd?.(entity)}
                className="rounded-full border-0 bg-[color-mix(in_srgb,var(--panel)_50%,transparent)] px-3 py-1 text-xs text-(--t-2) hover:border-primary hover:text-(--t-1)"
              >
                + Add {entity.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default EntityChips;
