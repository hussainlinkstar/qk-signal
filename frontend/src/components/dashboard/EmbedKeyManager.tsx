"use client";

import React, { useMemo, useState } from "react";
import { Trash2, KeyRound } from "lucide-react";
import Button from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassComponents";
import TextField from "@/components/ui/TextField";
import type {
  WorkspaceEmbedKeyCreatePayload,
  WorkspaceEmbedKeySummary,
} from "@/services/workspaceService";

type EmbedKeyManagerProps = {
  items: WorkspaceEmbedKeySummary[];
  creating: boolean;
  revokingKeyId: number | null;
  latestRawKey: string | null;
  onCreate: (payload: WorkspaceEmbedKeyCreatePayload) => Promise<void>;
  onRevoke: (id: number) => Promise<void>;
};

export default function EmbedKeyManager({
  items,
  creating,
  revokingKeyId,
  latestRawKey,
  onCreate,
  onRevoke,
}: EmbedKeyManagerProps) {
  const [label, setLabel] = useState("");
  const [originsText, setOriginsText] = useState("");
  const [dailyLimit, setDailyLimit] = useState("100");

  const parsedOrigins = useMemo(
    () =>
      originsText
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    [originsText]
  );

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onCreate({
      label,
      allowed_origins: parsedOrigins,
      daily_limit: Number(dailyLimit) || 100,
    });
    setLabel("");
    setOriginsText("");
  };

  return (
    <GlassCard className="space-y-4 p-5">
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-primary" />
        <p className="text-sm font-semibold text-(--t-1)">Embed Key Manager</p>
      </div>

      <form className="grid gap-3 md:grid-cols-2" onSubmit={submit}>
        <TextField
          label="Key Label"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="Homepage Widget"
          required
        />
        <TextField
          label="Daily Limit"
          type="number"
          value={dailyLimit}
          onChange={(event) => setDailyLimit(event.target.value)}
          min={1}
          max={50000}
          required
        />
        <div className="md:col-span-2">
          <TextField
            label="Allowed Origins (comma separated)"
            value={originsText}
            onChange={(event) => setOriginsText(event.target.value)}
            placeholder="https://agency.com, https://www.agency.com"
            required
          />
        </div>
        <div className="md:col-span-2 flex justify-end">
          <Button type="submit" loading={creating} loadingText="Creating...">
            Create Embed Key
          </Button>
        </div>
      </form>

      {latestRawKey ? (
        <div className="rounded-xl border-0 bg-amber-500/10 p-3 text-xs text-amber-200">
          <p className="font-bold uppercase tracking-wider">Copy this key now</p>
          <p className="mt-2 break-all font-mono">{latestRawKey}</p>
        </div>
      ) : null}

      <div className="space-y-2">
        {items.length === 0 ? (
          <p className="text-sm text-(--t-2)">No embed keys yet.</p>
        ) : (
          items.map((item) => (
            <div
              key={item.id}
              className="flex flex-col gap-2 rounded-xl border-0 bg-(--surface-subtle) p-3 md:flex-row md:items-center md:justify-between"
            >
              <div className="space-y-1">
                <p className="text-sm font-semibold text-(--t-1)">{item.label}</p>
                <p className="text-xs text-(--t-2)">
                  {item.key_prefix}
                  ****{item.key_last_four || "----"} · limit {item.daily_limit}/day
                </p>
                <p className="text-xs text-(--t-3)">{item.allowed_origins.join(", ")}</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onRevoke(item.id)}
                loading={revokingKeyId === item.id}
                loadingText="Revoking..."
              >
                <Trash2 className="h-4 w-4" />
                Revoke
              </Button>
            </div>
          ))
        )}
      </div>
    </GlassCard>
  );
}
