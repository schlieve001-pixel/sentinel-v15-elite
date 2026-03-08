export const API_BASE = import.meta.env.VITE_API_URL || "";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("vf_token");
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  // Only inject sim header if admin (set by auth context)
  const sim = localStorage.getItem("vf_simulate");
  const isAdmin = localStorage.getItem("vf_is_admin") === "1";
  if (sim && token && isAdmin) headers["X-Verifuse-Simulate"] = sim;
  return headers;
}

async function request<T>(path: string, opts: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    signal,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) {
    localStorage.removeItem("vf_token");
    localStorage.removeItem("vf_simulate");
    localStorage.removeItem("vf_is_admin");
    window.location.replace("/login");
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Request failed");
  }
  return res.json();
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// ── Auth ──────────────────────────────────────────────────────────

export interface AuthUser {
  user_id: string;
  email: string;
  full_name: string;
  firm_name: string;
  tier: string;
  credits_remaining: number;
  credits_pct_remaining?: number;
  upgrade_recommended?: boolean;
  monthly_grant?: number;
  bar_number?: string;
  unlocked_assets?: number;
  is_active?: boolean;
  is_admin?: boolean;
  email_verified?: boolean;
  role?: string;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export function register(data: {
  email: string;
  password: string;
  full_name: string;
  firm_name: string;
  bar_number: string;
  tier?: string;
}): Promise<AuthResponse> {
  return request("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function login(email: string, password: string): Promise<AuthResponse> {
  return request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function getMe(signal?: AbortSignal): Promise<AuthUser> {
  return request("/api/auth/me", {}, signal);
}

export function sendVerification(): Promise<{ ok: boolean; message: string; dev_code?: string }> {
  return request("/api/auth/send-verification", { method: "POST" });
}

export function verifyEmail(code: string): Promise<{ status: string }> {
  return request("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

// ── Preview ──────────────────────────────────────────────────────

export interface PreviewLead {
  preview_key: string;
  county: string;
  sale_month: string | null;
  data_grade: string;
  surplus_band: string | null;
}

export interface PreviewLeadsResponse {
  count: number;
  leads: PreviewLead[];
}

export function getPreviewLeads(params?: {
  county?: string;
  limit?: number;
  offset?: number;
}, signal?: AbortSignal): Promise<PreviewLeadsResponse> {
  const qs = new URLSearchParams();
  if (params?.county) qs.set("county", params.county);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return request(`/api/preview/leads${q ? `?${q}` : ""}`, {}, signal);
}

// ── Leads ─────────────────────────────────────────────────────────

export interface SurplusMathAudit {
  html_overbid: number | null;
  successful_bid: number | null;
  total_indebtedness: number | null;
  computed_surplus: number | null;
  voucher_overbid: number | null;
  voucher_doc_id: string | null;
  match_html_math: number | null;  // 1 = match, 0 = mismatch, null = n/a
  match_voucher: number | null;
  audit_grade: string | null;
  audit_notes: string | null;
  snapshot_id: string | null;
  doc_id: string | null;
}

export interface LienRecord {
  lien_type: string;       // "IRS", "HOA", "MORTGAGE", "JUDGMENT", "OTHER"
  lienholder_name?: string | null;
  priority?: number | null;
  amount_cents: number;    // lien amount in cents
  is_open: number;         // 1 = open/active, 0 = released
}

export interface Lead {
  asset_id: string;
  county: string;
  state: string;
  case_number: string | null;
  asset_type: string;
  estimated_surplus: number;
  surplus_verified: boolean;
  data_grade: string;
  record_class: string;
  sale_date: string | null;
  claim_deadline: string | null;
  days_to_claim: number | null;
  deadline_passed: boolean | null;
  // C.R.S. § 38-38-111 restriction period
  restriction_status: "RESTRICTED" | "WATCHLIST" | "ACTIONABLE" | "EXPIRED" | "UNKNOWN";
  // Internal DB label: DATA_ACCESS_ONLY | ESCROW_ENDED | EXPIRED | UNKNOWN
  statute_window_status?: string;
  restriction_end_date: string | null;
  blackout_end_date: string | null;
  days_until_actionable: number | null;
  address_hint: string;
  owner_img: string | null;
  completeness_score: number;
  data_age_days: number | null;
  preview_key?: string;        // null if not preview-eligible
  unlocked_by_me?: boolean;    // true if current user unlocked
  // Gate 7: canonical asset_registry key (FORECLOSURE:CO:{county}:{case})
  registry_asset_id?: string | null;
  // Gate 7: equity resolution fields (populated when equity_resolution row exists)
  gross_surplus_cents?: number | null;
  net_owner_equity_cents?: number | null;
  classification?: string | null;
  // Phase 4: forensic audit data (unlocked leads only)
  surplus_math_audit?: SurplusMathAudit | null;
  equity_resolution_notes?: string | null;
  // Surplus stream + estate case
  surplus_stream?: string | null;
  has_deceased_indicator?: number | null;
  // Domain model: enriched status fields
  sale_status?: "PRE_SALE" | "POST_SALE" | "UNKNOWN";
  timeline_flags?: string[];
  ready_to_file?: boolean;
  grade_reasons?: string[];
  // Verification state machine (Phase 4)
  verification_state?: "RAW" | "EXTRACTED" | "EVIDENCE_ATTACHED" | "MATH_VERIFIED" | "ATTORNEY_READY" | "PUBLISHED";
  pool_source?: "VOUCHER" | "LEDGER" | "HTML_MATH" | "UNVERIFIED";
  calc_hash?: string | null;
  current_calc_id?: string | null;
  last_verified_ts?: string | null;       // ISO 8601 (Phase 17)
  // Two-tier display (Phase 5)
  display_tier?: "POTENTIAL" | "VERIFIED";
  net_to_owner_label?: string;            // "VERIFIED NET TO OWNER" | "OVERBID POOL (Potential)"
  confidence_reasons?: string[];
  missing_inputs?: string[];
  // Junior liens and encumbrances (always included when data available)
  junior_liens?: LienRecord[];
  // EPIC 2D: evidence quality badge
  quality_badge?: "VERIFIED" | "PARTIAL" | "ESTIMATED";
  // EPIC 4B: AI opportunity score 0-10
  opportunity_score?: number | null;
  // EPIC 1C: owner name (may be masked for locked leads)
  owner_name?: string | null;
  property_address?: string | null;
  overbid_amount?: number | null;
}

export interface LeadsResponse {
  count: number;
  leads: Lead[];
}

// ── Pre-Sale Pipeline ──────────────────────────────────────────────

export interface PreSaleLead {
  id: string;
  county: string;
  case_number: string | null;
  owner_name: string | null;
  property_address: string | null;
  scheduled_sale_date: string | null;
  sale_date: string | null;
  ned_recorded_date: string | null;
  opening_bid: number;
  surplus_amount: number | null;
  overbid_amount: number | null;
  lender_name: string | null;
  ned_source: string | null;
  data_grade: string;
  ingestion_source: string | null;
  updated_at: string | null;
}

export interface CountyBreakdown {
  county: string;
  cnt: number;
  with_owner: number;
  with_surplus: number;
  pipeline_surplus: number;
}

export interface PreSaleResponse {
  count: number;
  total: number;
  limit: number;
  offset: number;
  county_breakdown: CountyBreakdown[];
  leads: PreSaleLead[];
}

export function getPreSaleLeads(params?: {
  county?: string;
  has_data?: boolean;
  limit?: number;
  offset?: number;
}, signal?: AbortSignal): Promise<PreSaleResponse> {
  const qs = new URLSearchParams();
  if (params?.county) qs.set("county", params.county);
  if (params?.has_data) qs.set("has_data", "true");
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return request(`/api/leads/pre-sale${q ? `?${q}` : ""}`, {}, signal);
}

export function getLeads(params?: {
  county?: string;
  min_surplus?: number;
  max_surplus?: number;
  grade?: string;
  bucket?: string;
  limit?: number;
  offset?: number;
  sale_date_from?: string;
  sale_date_to?: string;
  sort?: string;
  actionable_only?: boolean;
  verification_state?: string;
}, signal?: AbortSignal): Promise<LeadsResponse> {
  const qs = new URLSearchParams();
  if (params?.county) qs.set("county", params.county);
  if (params?.min_surplus) qs.set("min_surplus", String(params.min_surplus));
  if (params?.max_surplus) qs.set("max_surplus", String(params.max_surplus));
  if (params?.grade) qs.set("grade", params.grade);
  if (params?.bucket) qs.set("bucket", params.bucket);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.sale_date_from) qs.set("sale_date_from", params.sale_date_from);
  if (params?.sale_date_to) qs.set("sale_date_to", params.sale_date_to);
  if (params?.sort) qs.set("sort", params.sort);
  if (params?.actionable_only) qs.set("actionable_only", "1");
  if (params?.verification_state) qs.set("verification_state", params.verification_state);
  const q = qs.toString();
  return request(`/api/leads${q ? `?${q}` : ""}`, {}, signal);
}

export function getLeadDetail(assetId: string, signal?: AbortSignal): Promise<Lead> {
  return request(`/api/lead/${assetId}`, {}, signal);
}

// ── Stats ─────────────────────────────────────────────────────────

export interface Stats {
  total_assets: number;
  total_leads: number;
  attorney_ready: number;
  gold_grade: number;
  silver_grade: number;
  bronze_grade: number;
  reject_grade: number;
  total_claimable_surplus: number;
  verified_pipeline: number;
  verified_pipeline_surplus?: number;
  total_raw_volume: number;
  total_raw_volume_surplus?: number;
  county_list: string[];
  counties_covered?: number;
  new_leads_7d?: number;
  counties: { county: string; cnt: number; total: number }[];
  stream_breakdown?: { stream: string; cnt: number; total: number }[];
  pre_sale_count?: number;
  pre_sale_pipeline_surplus?: number;
}

export function getStats(signal?: AbortSignal): Promise<Stats> {
  return request("/api/stats", {}, signal);
}

// ── Unlock ────────────────────────────────────────────────────────

export interface UnlockResponse {
  asset_id: string;
  owner_name: string | null;
  property_address: string | null;
  county: string | null;
  case_number: string | null;
  estimated_surplus: number;
  total_indebtedness: number | null;
  overbid_amount: number | null;
  sale_date: string | null;
  days_remaining: number | null;
  statute_window: string | null;
  recorder_link: string | null;
  data_grade: string | null;
  confidence_score: number | null;
  source_doc_count?: number;
  credits_remaining?: number;
}

export function unlockLead(assetId: string): Promise<UnlockResponse> {
  return request(`/api/unlock/${assetId}`, { method: "POST" });
}

// ── Restricted Unlock ─────────────────────────────────────────────

export function unlockRestrictedLead(
  assetId: string,
  disclaimerAccepted: boolean
): Promise<UnlockResponse & { disclaimer_accepted: boolean; attorney_exemption: string }> {
  return request(`/api/unlock-restricted/${assetId}`, {
    method: "POST",
    body: JSON.stringify({ disclaimer_accepted: disclaimerAccepted }),
  });
}

// ── Downloads ────────────────────────────────────────────────────

export async function downloadSecure(path: string, fallbackFilename: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders(),
  });
  if (res.status === 401) {
    localStorage.removeItem("vf_token");
    localStorage.removeItem("vf_simulate");
    localStorage.removeItem("vf_is_admin");
    window.location.replace("/login");
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Download failed");
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition");
  let filename = fallbackFilename;
  if (disposition) {
    const match = disposition.match(/filename="?([^";\n]+)"?/);
    if (match) filename = match[1];
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function downloadSample(previewKey: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/dossier/sample/${previewKey}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Download failed");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `sample_dossier_${previewKey.slice(0, 8)}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Attorney Tools ───────────────────────────────────────────────

export function generateLetter(assetId: string): Promise<Blob> {
  return fetch(`${API_BASE}/api/letter/${assetId}`, {
    method: "POST",
    headers: authHeaders(),
  }).then((res) => {
    if (!res.ok) throw new ApiError(res.status, "Letter generation failed");
    return res.blob();
  });
}

export function getAttorneyReadyLeads(params?: {
  limit?: number;
  offset?: number;
}): Promise<LeadsResponse> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return request(`/api/leads/attorney-ready${q ? `?${q}` : ""}`);
}

// ── Billing ───────────────────────────────────────────────────────

export function createCheckout(tier: string): Promise<{ checkout_url: string }> {
  return request("/api/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ tier }),
  });
}

// ── Gate 7: Evidence documents (attorney-gated) ───────────────────

export interface EvidenceDoc {
  id: string;
  asset_id: string;
  filename: string;
  doc_type: string;
  doc_family: string;
  doc_family_label?: string;
  file_sha256: string;
  bytes: number;
  content_type: string;
  retrieved_ts: number;
}

/** List evidence documents for a captured GovSoft asset (attorney/admin only). */
export function getAssetEvidence(assetId: string, signal?: AbortSignal): Promise<EvidenceDoc[]> {
  return request(`/api/assets/${encodeURIComponent(assetId)}/evidence`, {}, signal);
}

/** Stream a vault evidence document (attorney/admin only). */
export function downloadEvidenceDoc(docId: string): Promise<Blob> {
  return fetch(`${API_BASE}/api/evidence/${encodeURIComponent(docId)}/download`, {
    headers: authHeaders(),
  }).then((res) => {
    if (!res.ok) throw new ApiError(res.status, "Evidence download failed");
    return res.blob();
  });
}

/** Full forensic audit trail for a lead (admin only). */
export function getLeadAudit(leadId: string, signal?: AbortSignal): Promise<LeadAuditTrail> {
  return request(`/api/admin/lead-audit/${encodeURIComponent(leadId)}`, {}, signal);
}

export interface LeadAuditEntry {
  id: string;
  user_email?: string;
  action: string;
  created_at: string;
  ip?: string;
  meta?: Record<string, unknown>;
  meta_json?: string;
}

export interface LeadAuditDoc {
  id: string;
  filename: string;
  doc_family?: string;
  bytes?: number;
  retrieved_ts?: number;
}

export interface LeadAuditTrail {
  lead: Record<string, unknown>;
  math_audit: Record<string, unknown> | null;
  equity_resolution: Record<string, unknown> | null;
  field_evidence: Record<string, unknown>[];
  evidence_docs: LeadAuditDoc[];
  pipeline_events: Record<string, unknown>[];
  audit_entries: LeadAuditEntry[];
  unlock_history: Record<string, unknown>[];
}

// ── Search ────────────────────────────────────────────────────────

export interface SearchResult {
  asset_id: string;
  case_number: string | null;
  property_address: string | null;
  county: string;
  data_grade: string;
  overbid_amount: number | null;
}

export function searchLeads(q: string, limit = 20, signal?: AbortSignal): Promise<SearchResult[]> {
  return request(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`, {}, signal);
}

// ── Coverage Map ──────────────────────────────────────────────────

export interface CountyCoverage {
  county_slug: string;
  county_name: string;
  status: "active" | "partial" | "configured" | "no_data";
  gold_count: number;
  silver_count: number;
  bronze_count: number;
  total_leads: number;
  last_scraped_at: string | null;
  access_method: string;
}

export function getCoverageMap(signal?: AbortSignal): Promise<CountyCoverage[]> {
  return request("/api/coverage-map", {}, signal);
}

// ── Case Timeline ─────────────────────────────────────────────────

export interface TimelineEvent {
  ts: string | null;
  event_type: string;
  notes: string | null;
  source: "pipeline" | "audit";
}

export function getLeadTimeline(assetId: string, signal?: AbortSignal): Promise<TimelineEvent[]> {
  return request(`/api/lead/${encodeURIComponent(assetId)}/timeline`, {}, signal);
}

// ── Title Stack ───────────────────────────────────────────────────

export interface TitleStack {
  liens: Array<{
    id: string;
    lien_type: string;
    lienholder_name: string | null;
    priority: number;
    amount_cents: number;
    is_open: number;
    source: string | null;
  }>;
  risk_score: "LOW" | "MEDIUM" | "HIGH";
  total_open_cents: number;
}

export function getLeadTitleStack(assetId: string, signal?: AbortSignal): Promise<TitleStack> {
  return request(`/api/lead/${encodeURIComponent(assetId)}/title-stack`, {}, signal);
}

// ── Attorney Cases ─────────────────────────────────────────────────

export type CaseStage = "LEADS" | "CONTACTED" | "RETAINER_SIGNED" | "FILED" | "FUNDS_RELEASED";

export interface AttorneyCase {
  id: string;
  asset_id: string;
  stage: CaseStage;
  notes: string | null;
  outcome_type: string | null;
  created_at: string;
  updated_at: string;
  case_number: string;
  county: string;
  data_grade: string;
  overbid_amount: number | null;
  property_address: string | null;
  sale_date: string | null;
}

export function getMyCases(signal?: AbortSignal): Promise<AttorneyCase[]> {
  return request("/api/my-cases", {}, signal);
}

export function createMyCase(data: { asset_id: string; stage?: CaseStage; notes?: string }): Promise<{ id: string; asset_id: string; stage: string }> {
  return request("/api/my-cases", { method: "POST", body: JSON.stringify(data) });
}

export function updateMyCase(caseId: string, data: Partial<{ stage: CaseStage; notes: string; outcome_type: string; outcome_notes: string; outcome_funds_cents: number }>): Promise<{ status: string }> {
  return request(`/api/my-cases/${caseId}`, { method: "PATCH", body: JSON.stringify(data) });
}

export function deleteMyCase(caseId: string): Promise<{ status: string }> {
  return request(`/api/my-cases/${caseId}`, { method: "DELETE" });
}

// ── Territories ───────────────────────────────────────────────────

export interface Territory {
  id: number;
  territory_type: string;
  territory_value: string;
  locked_at: string;
  expires_at: string | null;
}

export function getTerritories(signal?: AbortSignal): Promise<Territory[]> {
  return request("/api/territories", {}, signal);
}

export function lockTerritory(data: { territory_type: string; territory_value: string }): Promise<{ status: string; territory: string }> {
  return request("/api/territories", { method: "POST", body: JSON.stringify(data) });
}

export function releaseTerritory(id: number): Promise<{ status: string }> {
  return request(`/api/territories/${id}`, { method: "DELETE" });
}

// ── Admin API Keys ────────────────────────────────────────────────

export function generateApiKey(userId: number): Promise<{ api_key: string; created_at: string; note: string }> {
  return request(`/api/admin/users/${userId}/api-key`, { method: "POST" });
}

export function getApiKeyStatus(userId: number): Promise<{ has_key: boolean; created_at: string | null }> {
  return request(`/api/admin/users/${userId}/api-key-status`);
}

export function revokeApiKey(userId: number): Promise<{ status: string }> {
  return request(`/api/admin/users/${userId}/api-key`, { method: "DELETE" });
}
