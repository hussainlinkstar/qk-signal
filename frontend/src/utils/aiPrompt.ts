export const generateSEOStrategyPrompt = (auditData: any) => {
  return `You are a Senior SEO Strategy Expert and Data Analyst.
Analyze the following raw dataset from a technical audit:
${JSON.stringify(auditData)}.

OBJECTIVE:
Transform technical findings into an actionable business plan.

RESPONSE STRUCTURE (must be valid JSON):
1. "executive_summary": A single impactful sentence about the overall status.
2. "critical_alerts": Top 2 issues causing immediate revenue/traffic loss.
3. "priority_roadmap": A list of objects { task, category, impact, effort_score, reasoning }.
4. "content_gap_theory": Analyze keywords and suggest 3 new content opportunity areas.
5. "technical_debt_explanation": Briefly explain why performance score (LCP/CLS) affects conversions.

TONE:
Professional, authoritative, but easy to understand for non-technical stakeholders.`;
};
