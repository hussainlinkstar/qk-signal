export const AUDIT_CATEGORIES = [
  { value: "SaaS - B2B Software Platform", label: "SaaS - B2B Software Platform" },
  { value: "E-commerce - Online Retail Store", label: "E-commerce - Online Retail Store" },
  { value: "Finance - Financial Services", label: "Finance - Financial Services" },
  { value: "Healthcare - Medical Practice", label: "Healthcare - Medical Practice" },
  { value: "Travel - Tourism & Hospitality", label: "Travel - Tourism & Hospitality" },
  { value: "Media & Publishing", label: "Media & Publishing" },
  { value: "Agency - Marketing / Creative", label: "Agency - Marketing / Creative" },
  { value: "Technology - Product Company", label: "Technology - Product Company" },
  { value: "Local Business - Dental Clinic", label: "Local Business - Dental Clinic" },
  { value: "Local Business - Law Firm", label: "Local Business - Law Firm" },
  { value: "Local Business - HVAC Services", label: "Local Business - HVAC Services" },
  { value: "Local Business - Real Estate Agency", label: "Local Business - Real Estate Agency" },
  { value: "Local Business - Plumbing Services", label: "Local Business - Plumbing Services" },
  { value: "Local Business - Roofing Services", label: "Local Business - Roofing Services" },
  {
    value: "Local Business - Event Planner & Wedding Services",
    label: "Local Business - Event Planner & Wedding Services",
  },
  { value: "Local Business - Wedding Florist", label: "Local Business - Wedding Florist" },
  { value: "Local Business - Service Provider", label: "Local Business - Service Provider" },
  { value: "Personal Brand / Expert Site", label: "Personal Brand / Expert Site" },
  { value: "Events & Conferences", label: "Events & Conferences" },
  { value: "General Business Website", label: "General Business Website" },
] as const;

export const AUDIT_CATEGORY_VALUES = AUDIT_CATEGORIES.map((category) => category.value);
