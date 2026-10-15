"use client";

import React from "react";
import { useAuth } from "@/components/auth/custom-auth";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import Card from "@/components/ui/Card";
import SelectField from "@/components/ui/SelectField";
import BrandAssociationCard from "@/components/dashboard/entities/BrandAssociationCard";
import EntityImportanceHeatmap from "@/components/dashboard/entities/EntityImportanceHeatmap";
import KnowledgeGraph from "@/components/dashboard/entities/KnowledgeGraph";
import SemanticOpportunitiesTable from "@/components/dashboard/entities/SemanticOpportunitiesTable";
import SemanticVenn from "@/components/dashboard/entities/SemanticVenn";
import WelcomeOnboardingCard from "@/components/dashboard/WelcomeOnboardingCard";
import { fetchCompetitorMatrix, type CompetitorMatrixRow } from "@/services/competitorsService";
import { fetchSemanticGap, fetchSiteMap } from "@/services/semanticFootprintService";
import type { EntityCategory, SemanticGapPayload, SiteMapPayload } from "@/types/semanticFootprint";

export default function SemanticFootprintDashboard() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { getToken, isSignedIn } = useAuth();
  const [category, setCategory] = React.useState<EntityCategory | "all">("all");
  const [selectedEntity, setSelectedEntity] = React.useState<string>("");
  const [competitors, setCompetitors] = React.useState<CompetitorMatrixRow[]>([]);
  const [competitorsLoading, setCompetitorsLoading] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [notice, setNotice] = React.useState<string>("");
  const [error, setError] = React.useState<string>("");
  const [siteMap, setSiteMap] = React.useState<SiteMapPayload | null>(null);
  const [semanticGap, setSemanticGap] = React.useState<SemanticGapPayload | null>(null);

  const selectedSiteId = React.useMemo(() => {
    const rawSiteId = searchParams.get("siteId") ?? "";
    const parsed = Number(rawSiteId);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, [searchParams]);

  const selectedCompetitorSiteId = React.useMemo(() => {
    const rawCompetitorSiteId = searchParams.get("competitorSiteId") ?? "";
    const parsed = Number(rawCompetitorSiteId);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, [searchParams]);

  const getHeaders = React.useCallback(async (): Promise<Record<string, string>> => {
    const token = await getToken();
    if (!token) {
      throw new Error("Sign in required");
    }

    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  React.useEffect(() => {
    const loadCompetitors = async () => {
      if (!selectedSiteId) {
        setCompetitors([]);
        return;
      }

      if (!isSignedIn) {
        return;
      }

      setCompetitorsLoading(true);
      try {
        const headers = await getHeaders();
        const payload = await fetchCompetitorMatrix(selectedSiteId, headers);
        setCompetitors(payload);
      } catch {
        setCompetitors([]);
      } finally {
        setCompetitorsLoading(false);
      }
    };

    void loadCompetitors();
  }, [getHeaders, isSignedIn, selectedSiteId]);

  React.useEffect(() => {
    let active = true;

    const load = async () => {
      if (!selectedSiteId) {
        setNotice("Select a site to load semantic footprint data.");
        setError("");
        setSiteMap(null);
        setSemanticGap(null);
        setLoading(false);
        return;
      }

      if (!selectedCompetitorSiteId) {
        setNotice("Select a competitor to compare semantic footprint gaps.");
        setError("");
        setSiteMap(null);
        setSemanticGap(null);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const headers = await getHeaders();
        const [siteMapPayload, semanticGapPayload] = await Promise.all([
          fetchSiteMap(selectedSiteId, headers),
          fetchSemanticGap(selectedSiteId, selectedCompetitorSiteId, headers),
        ]);

        if (!active) return;
        setSiteMap(siteMapPayload);
        setSemanticGap(semanticGapPayload);
        setNotice("");
        setError("");
      } catch (err) {
        if (!active) return;
        setNotice("");
        setError(err instanceof Error ? err.message : "Unable to load semantic footprint data.");
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();

    return () => {
      active = false;
    };
  }, [getHeaders, selectedSiteId, selectedCompetitorSiteId]);

  const categories = React.useMemo(() => semanticGap?.categories ?? [], [semanticGap]);

  const filtered = React.useMemo(() => {
    if (!semanticGap) return null;
    if (category === "all") return semanticGap;

    return {
      ...semanticGap,
      venn: semanticGap.venn.filter((item) => item.category === category),
      heatmap: semanticGap.heatmap.filter((item) => item.category === category),
      opportunities: semanticGap.opportunities.filter((item) => item.category === category),
    };
  }, [semanticGap, category]);

  const sourceEntities = React.useMemo(() => {
    if (!siteMap) return [];
    if (!selectedEntity) return siteMap.entities;
    return siteMap.entities.filter((item) => item.normalizedKey === selectedEntity);
  }, [siteMap, selectedEntity]);

  const onChangeCompetitor = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const params = new URLSearchParams(searchParams.toString());
    const nextId = event.target.value;

    if (!nextId) {
      params.delete("competitorSiteId");
    } else {
      params.set("competitorSiteId", nextId);
    }

    router.push(params.toString() ? `${pathname}?${params.toString()}` : pathname);
  };

  if (loading) {
    return (
      <Card className="p-6 text-sm text-(--t-2)">Loading semantic footprint dashboard...</Card>
    );
  }

  if (!selectedSiteId || !selectedCompetitorSiteId || !filtered) {
    return (
      <section className="space-y-6" aria-label="semantic-footprint-dashboard">
        <header>
          <h1 className="text-3xl font-black text-(--t-1)">Semantic Footprint Dashboard</h1>
          <p className="mt-2 text-sm font-medium text-(--t-2)">
            Analyze entity coverage, overlap, and semantic gaps against your selected competitor.
          </p>
        </header>

        <Card className="space-y-4 p-6">
          <label className="block space-y-1 text-sm text-(--t-1)">
            Compare with competitor
            <SelectField
              aria-label="Compare with competitor"
              value={selectedCompetitorSiteId ? String(selectedCompetitorSiteId) : ""}
              onChange={onChangeCompetitor}
              disabled={!selectedSiteId || competitorsLoading || competitors.length === 0}
            >
              <option value="">No competitor selected</option>
              {competitors.map((item) => (
                <option key={item.id} value={String(item.id)}>
                  {item.name}
                </option>
              ))}
            </SelectField>
            {!selectedSiteId ? (
              <p className="text-xs text-(--t-2)">
                Select a site first to load available competitors.
              </p>
            ) : competitorsLoading ? (
              <p className="text-xs text-(--t-2)">Loading competitors…</p>
            ) : competitors.length === 0 ? (
              <p className="text-xs text-(--t-2)">
                No linked competitors found for this site. Add one from the Competitors page.
              </p>
            ) : (
              <p className="text-xs text-(--t-2)">
                Pick a competitor to unlock semantic gap comparisons.
              </p>
            )}
          </label>
        </Card>

        {(!selectedSiteId || !selectedCompetitorSiteId) && <WelcomeOnboardingCard />}

        {selectedSiteId && selectedCompetitorSiteId && !filtered && !notice && !error && (
          <WelcomeOnboardingCard />
        )}

        {notice ? (
          <div className="rounded-xl border-0 bg-cyan-900/10 px-4 py-3 text-sm font-medium text-(--purple) shadow-inner">
            {notice}
          </div>
        ) : null}
        {error ? (
          <div className="rounded-xl border-0 bg-rose-500/10 px-4 py-3 text-sm font-medium text-rose-300 shadow-inner">
            {error}
          </div>
        ) : null}
      </section>
    );
  }

  return (
    <section className="space-y-6" aria-label="semantic-footprint-dashboard">
      <header>
        <h1 className="text-3xl font-black text-(--t-1)">Semantic Footprint Dashboard</h1>
        <p className="mt-2 text-sm text-(--t-2)">
          Analyze entity coverage, overlap, and semantic gaps against your selected competitor.
        </p>
      </header>

      <Card className="space-y-4 p-6">
        <label className="block space-y-1 text-sm text-(--t-1)">
          Compare with competitor
          <SelectField
            aria-label="Compare with competitor"
            value={selectedCompetitorSiteId ? String(selectedCompetitorSiteId) : ""}
            onChange={onChangeCompetitor}
            disabled={!selectedSiteId || competitorsLoading || competitors.length === 0}
          >
            <option value="">No competitor selected</option>
            {competitors.map((item) => (
              <option key={item.id} value={String(item.id)}>
                {item.name}
              </option>
            ))}
          </SelectField>
          {!selectedSiteId ? (
            <p className="text-xs text-(--t-2)">
              Select a site first to load available competitors.
            </p>
          ) : competitorsLoading ? (
            <p className="text-xs text-(--t-2)">Loading competitors…</p>
          ) : competitors.length === 0 ? (
            <p className="text-xs text-(--t-2)">
              No linked competitors found for this site. Add one from the Competitors page.
            </p>
          ) : (
            <p className="text-xs text-(--t-2)">
              Pick a competitor to unlock semantic gap comparisons.
            </p>
          )}
        </label>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm text-(--t-1)">
            Entity category
            <SelectField
              aria-label="Entity category"
              value={category}
              onChange={(event) => setCategory(event.target.value as EntityCategory | "all")}
            >
              <option value="all">All categories</option>
              {categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </SelectField>
          </label>
          <label className="space-y-1 text-sm text-(--t-1)">
            Site map entity drill-down
            <SelectField
              aria-label="Site map entity drill-down"
              value={selectedEntity}
              onChange={(event) => setSelectedEntity(event.target.value)}
            >
              <option value="">All entities</option>
              {(siteMap?.entities ?? []).map((item) => (
                <option key={item.normalizedKey} value={item.normalizedKey}>
                  {item.name}
                </option>
              ))}
            </SelectField>
          </label>
        </div>
      </Card>

      {notice ? (
        <Card className="border-cyan-900/70 bg-cyan-950/20 p-4 text-sm text-cyan-100">
          {notice}
        </Card>
      ) : null}
      {error ? <Card className="p-4 text-sm text-rose-300">{error}</Card> : null}

      {filtered ? (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <SemanticVenn nodes={filtered.venn} />
            <KnowledgeGraph graphPayload={filtered.knowledgeGraph} siteMapPayload={siteMap} />
            <EntityImportanceHeatmap
              cells={filtered.heatmap}
              onSelectSourceUrl={setSelectedEntity}
            />
            <BrandAssociationCard
              associations={filtered.brandAssociations}
              onSelectSourceUrl={setSelectedEntity}
            />
          </div>

          <SemanticOpportunitiesTable
            rows={filtered.opportunities}
            onSelectSourceUrl={setSelectedEntity}
          />

          <Card className="p-6">
            <h3 className="text-xl font-bold tracking-tight text-(--t-1) mb-4">
              Entity drill-down results
            </h3>
            {sourceEntities.length === 0 ? (
              <p className="text-sm font-medium text-(--t-2)">
                No matching site map entities for the selected filters.
              </p>
            ) : (
              <ul className="space-y-2 text-sm font-medium text-(--t-2)">
                {sourceEntities.map((entry) => (
                  <li
                    key={entry.normalizedKey}
                    className="rounded-[14px] border-0 bg-[#EEF1F6] bg-(--line-2) p-3 flex justify-between items-center transition-colors hover:bg-(--line-2)"
                  >
                    <div>
                      <span className="font-bold text-(--t-1) mr-2">{entry.name}</span>
                      <span className="text-[10px] tracking-widest uppercase text-(--t-3)">
                        {entry.category}
                      </span>
                    </div>
                    <span className="text-[10px] tracking-widest uppercase text-(--t-2)">
                      Frequency{" "}
                      <span className="font-bold text-(--t-1) ml-1">{entry.frequency}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      ) : notice || error ? null : (
        <Card className="p-4 text-sm text-(--t-2)">No semantic footprint data available yet.</Card>
      )}
    </section>
  );
}
