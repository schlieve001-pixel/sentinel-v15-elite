const API_BASE = import.meta.env.VITE_API_URL || "";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("vf_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(opts.headers || {}),
    },
  });
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
  bar_number?: string;
  unlocked_assets?: number;
  is_active?: boolean;
  is_admin?: boolean;
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

export function getMe(): Promise<AuthUser> {
  return request("/api/auth/me");
}

// ── Leads ─────────────────────────────────────────────────────────

export interface Lead {
  asset_id: string;
  county: string;
  state: string;
  case_number: string;
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
  confidence_score: number;
  data_age_days: number | null;
}

export interface LeadsResponse {
  count: number;
  leads: Lead[];
}

export function getLeads(params?: {
  county?: string;
  min_surplus?: number;
  grade?: string;
  bucket?: string;
  limit?: number;
  offset?: number;
}): Promise<LeadsResponse> {
  const qs = new URLSearchParams();
  if (params?.county) qs.set("county", params.county);
  if (params?.min_surplus) qs.set("min_surplus", String(params.min_surplus));
  if (params?.grade) qs.set("grade", params.grade);
  if (params?.bucket) qs.set("bucket", params.bucket);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return request(`/api/leads${q ? `?${q}` : ""}`);
}

export function getLeadDetail(assetId: string): Promise<Lead> {
  return request(`/api/lead/${assetId}`);
}

// ── Stats ─────────────────────────────────────────────────────────

export interface Stats {
  total_assets: number;
  attorney_ready: number;
  gold_grade: number;
  total_claimable_surplus: number;
  counties: { county: string; cnt: number; total: number }[];
}

export function getStats(): Promise<Stats> {
  return request("/api/stats");
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
  motion_pdf: string | null;
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

// ── Dossier ───────────────────────────────────────────────────────

export function getDossierUrl(assetId: string): string {
  return `${API_BASE}/api/dossier/${assetId}`;
}

export function getDossierDocxUrl(assetId: string): string {
  return `${API_BASE}/api/dossier/${assetId}/docx`;
}

export function getDossierPdfUrl(assetId: string): string {
  return `${API_BASE}/api/dossier/${assetId}/pdf`;
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

export function getCasePacketUrl(assetId: string): string {
  return `${API_BASE}/api/case-packet/${assetId}`;
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
