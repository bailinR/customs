<script setup>
import { computed, onMounted, onUnmounted, reactive } from "vue";
import ComtradeSelect from "./components/ComtradeSelect.vue";

const meta = reactive({
  reporters: [],
  years: [],
  months: [],
  flows: [],
  frequencies: [],
});

const syncMeta = reactive({
  reporters: [],
  years: [],
  months: [],
  frequencies: [],
  slice_hints: [],
  loading: false,
});

const filters = reactive({
  reporter_code: "",
  year: "",
  month: "",
  freq_code: "A",
  flow_code: "",
  partner_name: "",
  partner_scope: "countries",
});

const syncForm = reactive({
  reporter_code: "",
  year: "",
  month: "0",
  freq_code: "A",
  force_refresh: false,
});

const PAGE_SIZE_OPTIONS = [20, 50, 100];
const NO_SCROLL_SIZE = 20;

const state = reactive({
  items: [],
  total: 0,
  page: 1,
  page_size: NO_SCROLL_SIZE,
  pages: 0,
  loading: false,
  error: "",
});

const syncState = reactive({
  syncing: false,
  error: "",
  result: null,
  progress: {
    current: 0,
    total: 0,
    percent: 0,
    label: "",
  },
});

const exportState = reactive({
  exporting: false,
  error: "",
});

const activeView = reactive({ mode: "trade" });

const gaccMeta = reactive({
  flow_types: [],
  currencies: [],
  years: [],
  months: [],
  latest_year: 2026,
  latest_month: 4,
  default_year: 2026,
  default_month_start: 1,
  default_month_end: 1,
  max_month_by_year: {},
  output_field_options: [],
  default_output_fields: [],
  captcha_timeout_sec: 180,
  captcha_mode: "auto",
  captcha_auto_max_attempts: 5,
  captcha_fallback_manual: true,
  loading: false,
});

const gaccForm = reactive({
  flow_type: "import",
  currency: "USD",
  year: "",
  month_start: "1",
  month_end: "1",
  split_by_month: false,
  output_fields: ["CODE_TS", "ORIGIN_COUNTRY", "TRADE_MODE", "TRADE_CO_PORT"],
});

const gaccState = reactive({
  querying: false,
  error: "",
  jobId: "",
  job: null,
});

const gaccBrowseFilters = reactive({
  flow_type: "",
  currency: "",
  year: "",
  month: "",
});

const gaccBrowseState = reactive({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  pages: 0,
  loading: false,
});

let gaccPollTimer = null;

const sliceMeta = reactive({
  reporters: [],
  years: [],
  frequencies: [],
  statuses: [],
  empty_ttl_days: 7,
});

const sliceFilters = reactive({
  reporter_code: "",
  year: "",
  freq_code: "",
  status: "",
});

const sliceState = reactive({
  items: [],
  summary: { total: 0, ok: 0, empty: 0, error: 0 },
  total: 0,
  page: 1,
  page_size: 20,
  pages: 0,
  loading: false,
  error: "",
});

const visiblePages = computed(() => {
  const total = state.pages;
  const current = state.page;
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages = new Set([1, total, current, current - 1, current + 1]);
  const sorted = [...pages]
    .filter((p) => p >= 1 && p <= total)
    .sort((a, b) => a - b);
  const result = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) {
      result.push("...");
    }
    result.push(sorted[i]);
  }
  return result;
});

const sliceVisiblePages = computed(() => {
  const total = sliceState.pages;
  const current = sliceState.page;
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages = new Set([1, total, current, current - 1, current + 1]);
  const sorted = [...pages]
    .filter((p) => p >= 1 && p <= total)
    .sort((a, b) => a - b);
  const result = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) {
      result.push("...");
    }
    result.push(sorted[i]);
  }
  return result;
});

const gaccVisiblePages = computed(() => {
  const total = gaccBrowseState.pages;
  const current = gaccBrowseState.page;
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages = new Set([1, total, current, current - 1, current + 1]);
  const sorted = [...pages]
    .filter((p) => p >= 1 && p <= total)
    .sort((a, b) => a - b);
  const result = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) {
      result.push("...");
    }
    result.push(sorted[i]);
  }
  return result;
});

const isTotalScope = computed(() => filters.partner_scope === "total");
const tableScrollable = computed(() => state.page_size > NO_SCROLL_SIZE);

const paddingCount = computed(() => {
  if (tableScrollable.value) return 0;
  return Math.max(0, state.page_size - state.items.length);
});

const tableStyle = computed(() => ({
  "--rows": state.page_size,
  "--visible-rows": tableScrollable.value ? NO_SCROLL_SIZE : state.page_size,
}));

const isMonthlySync = computed(() => syncForm.freq_code === "M");
const isMonthlyQuery = computed(() => filters.freq_code === "M");

const syncFormReady = computed(() => {
  if (!syncForm.reporter_code || !syncForm.year) return false;
  if (isMonthlySync.value && !syncForm.month) return false;
  return true;
});

const reporterSelectOptions = computed(() => [
  { value: "", label: "All" },
  ...syncMeta.reporters.map((r) => ({
    value: String(r.code),
    label: r.label || r.name_en,
  })),
]);

const yearSelectGroups = computed(() => {
  const years = syncMeta.years;
  if (!years.length) return [];
  const toOpt = (y) => ({ value: String(y), label: String(y) });
  return [{ label: "Recent periods", options: years.map(toOpt) }];
});

const syncMonthSelectGroups = computed(() => {
  if (!isMonthlySync.value || !syncForm.year) return [];
  const year = syncForm.year;
  const months = syncMeta.months.length
    ? syncMeta.months
    : Array.from({ length: 12 }, (_, i) => ({
        value: 12 - i,
        label: [
          "January",
          "February",
          "March",
          "April",
          "May",
          "June",
          "July",
          "August",
          "September",
          "October",
          "November",
          "December",
        ][11 - i],
      }));
  return [
    {
      label: year,
      options: [
        { value: "0", label: `All of ${year}` },
        ...months.map((m) => ({
          value: String(m.value),
          label: `${m.label} ${year}`,
        })),
      ],
    },
  ];
});

const currentSliceHint = computed(() => {
  if (!syncFormReady.value) return null;
  const reporter = Number(syncForm.reporter_code);
  const year = Number(syncForm.year);
  const freq = syncForm.freq_code;
  const month = freq === "M" ? Number(syncForm.month) : 0;
  const hints = syncMeta.slice_hints.filter((h) => {
    if (
      h.reporter_code !== reporter ||
      h.year !== year ||
      h.freq_code !== freq
    ) {
      return false;
    }
    if (freq === "A") return (h.month || 0) === 0;
    if (month === 0) return (h.month || 0) > 0;
    return Number(h.month) === month;
  });
  if (!hints.length) return null;
  if (freq === "M" && month === 0) {
    const okHints = hints.filter((h) => h.status === "ok");
    if (okHints.length) {
      return {
        status: "ok",
        record_count: okHints.reduce((s, h) => s + (h.record_count || 0), 0),
        fetched_at: okHints[0].fetched_at,
        month_count: okHints.length,
      };
    }
    const allEmpty = hints.every((h) => h.status === "empty");
    if (allEmpty) return hints[0];
    return hints[0];
  }
  const hasOk = hints.some((h) => h.status === "ok");
  if (hasOk) return hints.find((h) => h.status === "ok") || hints[0];
  const allEmpty = hints.every((h) => h.status === "empty");
  if (allEmpty) return hints[0];
  return hints[0];
});

function formatUsd(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatFetchedAt(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("zh-CN");
}

function isMonthFilterActive(month) {
  const n = Number(month);
  return Number.isInteger(n) && n >= 1 && n <= 12;
}

function buildFilterQuery() {
  const params = new URLSearchParams();
  params.set("freq_code", filters.freq_code);
  if (filters.reporter_code) params.set("reporter_code", filters.reporter_code);
  if (filters.year) params.set("year", filters.year);
  if (filters.freq_code === "M" && isMonthFilterActive(filters.month)) {
    params.set("month", filters.month);
  }
  if (filters.flow_code) params.set("flow_code", filters.flow_code);
  if (filters.partner_name.trim())
    params.set("partner_name", filters.partner_name.trim());
  params.set("partner_scope", filters.partner_scope);
  return params.toString();
}

function buildQuery(page = state.page) {
  const params = new URLSearchParams(buildFilterQuery());
  params.set("page", String(page));
  params.set("page_size", String(state.page_size));
  return params.toString();
}

async function fetchMeta() {
  const params = new URLSearchParams();
  params.set("freq_code", filters.freq_code);
  if (filters.reporter_code) params.set("reporter_code", filters.reporter_code);
  if (filters.year) params.set("year", filters.year);
  if (filters.freq_code === "M" && isMonthFilterActive(filters.month)) {
    params.set("month", filters.month);
  }
  const qs = params.toString();
  const res = await fetch(`/api/meta/filters?${qs}`);
  if (!res.ok) throw new Error("加载筛选项失败");
  const data = await res.json();
  meta.reporters = data.reporters;
  meta.years = data.years;
  meta.months = data.months || [];
  meta.flows = data.flows;
  meta.frequencies = data.frequencies || [];
}

async function onReporterChange() {
  await fetchMeta();
  if (
    filters.year &&
    !meta.years.some((y) => String(y) === String(filters.year))
  ) {
    filters.year = "";
    filters.month = "";
    await fetchMeta();
  }
  if (
    isMonthFilterActive(filters.month) &&
    !meta.months.some((m) => String(m.value) === String(filters.month))
  ) {
    filters.month = "";
    await fetchMeta();
  }
}

async function onYearChange() {
  await fetchMeta();
  if (
    filters.reporter_code &&
    !meta.reporters.some(
      (r) => String(r.code) === String(filters.reporter_code),
    )
  ) {
    filters.reporter_code = "";
    await fetchMeta();
  }
  if (
    isMonthFilterActive(filters.month) &&
    !meta.months.some((m) => String(m.value) === String(filters.month))
  ) {
    filters.month = "";
    await fetchMeta();
  }
}

async function onMonthChange() {
  await fetchMeta();
  if (
    filters.reporter_code &&
    !meta.reporters.some(
      (r) => String(r.code) === String(filters.reporter_code),
    )
  ) {
    filters.reporter_code = "";
    await fetchMeta();
  }
  if (
    filters.year &&
    !meta.years.some((y) => String(y) === String(filters.year))
  ) {
    filters.year = "";
    await fetchMeta();
  }
}

async function onFreqChange() {
  if (filters.freq_code === "A") {
    filters.month = "";
  }
  await fetchMeta();
  await fetchTrade(1);
}

async function fetchSyncOptions() {
  syncMeta.loading = true;
  try {
    const res = await fetch("/api/meta/sync-options");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "加载同步选项失败");
    }
    const data = await res.json();
    syncMeta.reporters = data.reporters;
    syncMeta.years = data.years;
    syncMeta.months = data.months || [];
    syncMeta.frequencies = data.frequencies || [];
    syncMeta.slice_hints = data.slice_hints || [];

    if (!syncForm.reporter_code) {
      const china = data.reporters.find((r) => r.code === 156);
      const fallback = china || data.reporters[0];
      if (fallback) syncForm.reporter_code = String(fallback.code);
    }
    if (!syncForm.year && data.years.length) {
      syncForm.year = String(data.years[0]);
    }
  } finally {
    syncMeta.loading = false;
  }
}

async function fetchTrade(page = 1) {
  state.loading = true;
  state.error = "";
  try {
    const res = await fetch(`/api/trade?${buildQuery(page)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `请求失败 (${res.status})`);
    }
    const data = await res.json();
    state.items = data.items;
    state.total = data.total;
    state.page = data.page;
    state.pages = data.pages;
  } catch (e) {
    state.error = e.message || "加载失败";
    state.items = [];
    state.total = 0;
    state.pages = 0;
  } finally {
    state.loading = false;
  }
}

function resetSyncProgress() {
  syncState.progress.current = 0;
  syncState.progress.total = 0;
  syncState.progress.percent = 0;
  syncState.progress.label = "";
}

function handleSyncStreamEvent(event) {
  if (event.type === "start") {
    syncState.progress.total = event.total || 0;
    syncState.progress.current = 0;
    syncState.progress.percent = 0;
    syncState.progress.label = "准备同步…";
    return null;
  }
  if (event.type === "progress") {
    syncState.progress.current = event.current || 0;
    syncState.progress.total = event.total || 0;
    syncState.progress.percent = event.percent || 0;
    syncState.progress.label = event.label || "";
    return null;
  }
  if (event.type === "done") {
    return event.result || null;
  }
  if (event.type === "error") {
    throw new Error(event.message || "同步失败");
  }
  return null;
}

async function consumeSyncStream(body) {
  const res = await fetch("/api/sync/slice/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `同步失败 (${res.status})`);
  }
  if (!res.body) {
    throw new Error("同步流不可用");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6));
      const result = handleSyncStreamEvent(event);
      if (result) finalResult = result;
    }
  }

  if (!finalResult) {
    throw new Error("同步未完成");
  }
  return finalResult;
}

async function applySyncSuccess(data) {
  syncState.result = data;
  await fetchSyncOptions();
  if (data.status === "ok") {
    filters.reporter_code = syncForm.reporter_code;
    filters.year = syncForm.year;
    filters.freq_code = syncForm.freq_code;
    filters.month =
      syncForm.freq_code === "M" && isMonthFilterActive(syncForm.month)
        ? syncForm.month
        : "";
    await fetchMeta();
    await fetchTrade(1);
  }
  if (activeView.mode === "slices") {
    await fetchSliceMeta();
    await fetchSlices(sliceState.page);
  }
}

function buildSliceQuery(page = sliceState.page) {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", String(sliceState.page_size));
  if (sliceFilters.reporter_code) {
    params.set("reporter_code", sliceFilters.reporter_code);
  }
  if (sliceFilters.year) params.set("year", sliceFilters.year);
  if (sliceFilters.freq_code) params.set("freq_code", sliceFilters.freq_code);
  if (sliceFilters.status) params.set("status", sliceFilters.status);
  return params.toString();
}

async function fetchSliceMeta() {
  const res = await fetch("/api/slices/meta");
  if (!res.ok) throw new Error("加载切片筛选项失败");
  const data = await res.json();
  sliceMeta.reporters = data.reporters || [];
  sliceMeta.years = data.years || [];
  sliceMeta.frequencies = data.frequencies || [];
  sliceMeta.statuses = data.statuses || [];
  sliceMeta.empty_ttl_days = data.empty_ttl_days || 7;
}

async function fetchSlices(page = 1) {
  sliceState.loading = true;
  sliceState.error = "";
  try {
    const res = await fetch(`/api/slices?${buildSliceQuery(page)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `加载切片状态失败 (${res.status})`);
    }
    const data = await res.json();
    sliceState.items = data.items || [];
    sliceState.summary = data.summary || {
      total: 0,
      ok: 0,
      empty: 0,
      error: 0,
    };
    sliceState.total = data.total || 0;
    sliceState.page = data.page || 1;
    sliceState.pages = data.pages || 0;
  } catch (e) {
    sliceState.error = e.message || "加载失败";
    sliceState.items = [];
    sliceState.total = 0;
    sliceState.pages = 0;
  } finally {
    sliceState.loading = false;
  }
}

async function switchView(mode) {
  activeView.mode = mode;
  if (mode === "slices") {
    try {
      await fetchSliceMeta();
      await fetchSlices(1);
    } catch (e) {
      sliceState.error = e.message || "加载切片状态失败";
    }
  }
  if (mode === "gacc") {
    try {
      await fetchGaccMeta();
      await fetchGaccBrowseList(1);
    } catch (e) {
      gaccState.error = e.message || "加载海关查询选项失败";
    }
  }
}

async function fetchGaccMeta() {
  gaccMeta.loading = true;
  try {
    const res = await fetch("/api/gacc/meta/options");
    if (!res.ok) throw new Error("加载海关查询选项失败");
    const data = await res.json();
    gaccMeta.flow_types = data.flow_types || [];
    gaccMeta.currencies = data.currencies || [];
    gaccMeta.years = data.years || [];
    gaccMeta.months = data.months || [];
    gaccMeta.latest_year = data.latest_year ?? 2026;
    gaccMeta.latest_month = data.latest_month ?? 4;
    gaccMeta.default_year = data.default_year ?? data.latest_year ?? 2026;
    gaccMeta.default_month_start = data.default_month_start ?? 1;
    gaccMeta.default_month_end = data.default_month_end ?? 1;
    gaccMeta.max_month_by_year = data.max_month_by_year || {};
    gaccMeta.output_field_options = data.output_field_options || [];
    gaccMeta.default_output_fields = data.default_output_fields || [];
    gaccMeta.captcha_timeout_sec = data.captcha_timeout_sec || 180;
    gaccMeta.captcha_mode = data.captcha_mode || "auto";
    gaccMeta.captcha_auto_max_attempts = data.captcha_auto_max_attempts || 5;
    gaccMeta.captcha_fallback_manual = data.captcha_fallback_manual !== false;
    gaccMeta.download_dir = data.download_dir || "data/gacc_downloads";
    if (!gaccForm.year) {
      applyGaccDefaults();
    } else {
      clampGaccMonths();
    }
    if (
      !gaccForm.output_fields.length &&
      gaccMeta.default_output_fields.length
    ) {
      gaccForm.output_fields = [...gaccMeta.default_output_fields];
    }
  } finally {
    gaccMeta.loading = false;
  }
}

function stopGaccPoll() {
  if (gaccPollTimer) {
    clearInterval(gaccPollTimer);
    gaccPollTimer = null;
  }
}

async function pollGaccJob() {
  if (!gaccState.jobId) return;
  try {
    const res = await fetch(`/api/gacc/jobs/${gaccState.jobId}`);
    if (!res.ok) throw new Error("查询任务状态失败");
    gaccState.job = await res.json();
    if (gaccState.job.status === "success") {
      stopGaccPoll();
      gaccState.querying = false;
      syncGaccBrowseFromQuery();
      await fetchGaccBrowseList(1);
    } else if (gaccState.job.status === "error") {
      stopGaccPoll();
      gaccState.querying = false;
      gaccState.error = gaccState.job.error_message || "采集失败";
    }
  } catch (e) {
    stopGaccPoll();
    gaccState.querying = false;
    gaccState.error = e.message || "轮询失败";
  }
}

function startGaccPoll() {
  stopGaccPoll();
  pollGaccJob();
  gaccPollTimer = setInterval(pollGaccJob, 1500);
}

async function fetchGaccBrowseList(page = 1) {
  gaccBrowseState.loading = true;
  gaccState.error = "";
  try {
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("page_size", String(gaccBrowseState.page_size));
    if (gaccBrowseFilters.flow_type) {
      params.set("flow_type", gaccBrowseFilters.flow_type);
    }
    if (gaccBrowseFilters.currency) {
      params.set("currency", gaccBrowseFilters.currency);
    }
    if (gaccBrowseFilters.year) {
      params.set("year", gaccBrowseFilters.year);
    }
    if (gaccBrowseFilters.month) {
      params.set("month", gaccBrowseFilters.month);
    }
    const res = await fetch(`/api/gacc/trade?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `加载失败 (${res.status})`);
    }
    const data = await res.json();
    gaccBrowseState.items = data.items || [];
    gaccBrowseState.total = data.total || 0;
    gaccBrowseState.page = data.page || 1;
    gaccBrowseState.pages = data.pages || 0;
  } catch (e) {
    gaccState.error = e.message || "加载失败";
    gaccBrowseState.items = [];
    gaccBrowseState.total = 0;
    gaccBrowseState.pages = 0;
  } finally {
    gaccBrowseState.loading = false;
  }
}

function syncGaccBrowseFromQuery() {
  gaccBrowseFilters.flow_type = gaccForm.flow_type;
  gaccBrowseFilters.currency = gaccForm.currency;
  gaccBrowseFilters.year = gaccForm.year;
  if (gaccForm.month_start === gaccForm.month_end) {
    gaccBrowseFilters.month = gaccForm.month_start;
  } else {
    gaccBrowseFilters.month = "";
  }
}

function onGaccBrowseSearch() {
  fetchGaccBrowseList(1);
}

function onGaccBrowseReset() {
  gaccBrowseFilters.flow_type = "";
  gaccBrowseFilters.currency = "";
  gaccBrowseFilters.year = "";
  gaccBrowseFilters.month = "";
  fetchGaccBrowseList(1);
}

function goGaccBrowsePage(page) {
  if (page < 1 || page > gaccBrowseState.pages || page === gaccBrowseState.page)
    return;
  fetchGaccBrowseList(page);
}

function onGaccBrowsePageSizeChange() {
  fetchGaccBrowseList(1);
}

const gaccFormReady = computed(() => {
  return (
    gaccForm.flow_type &&
    gaccForm.currency &&
    gaccForm.year &&
    gaccForm.month_start &&
    gaccForm.month_end
  );
});

const gaccMonthOptions = computed(() => {
  const year = Number(gaccForm.year);
  const max =
    gaccMeta.max_month_by_year[String(year)] ??
    gaccMeta.max_month_by_year[year] ??
    12;
  return Array.from({ length: max }, (_, i) => i + 1);
});

const gaccBrowseMonthOptions = computed(() => {
  if (!gaccBrowseFilters.year) {
    return gaccMeta.months.length
      ? gaccMeta.months
      : Array.from({ length: 12 }, (_, i) => i + 1);
  }
  const year = Number(gaccBrowseFilters.year);
  const max =
    gaccMeta.max_month_by_year[String(year)] ??
    gaccMeta.max_month_by_year[year] ??
    12;
  return Array.from({ length: max }, (_, i) => i + 1);
});

const gaccValueColumnLabel = computed(() => {
  if (gaccBrowseFilters.currency === "CNY") return "人民币";
  if (gaccBrowseFilters.currency === "USD") return "美元";
  return "金额";
});

function formatGaccNum(value) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatGaccQty(value, unit) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  if (n === 0 && !unit) return "—";
  const text = n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return unit ? `${text} ${unit}` : text;
}

function showGaccQty2(row) {
  if (row.qty2 == null || row.qty2 === "") return false;
  const n = Number(row.qty2);
  if (Number.isNaN(n)) return false;
  return n !== 0 || Boolean(row.unit2);
}

function applyGaccDefaults() {
  gaccForm.year = String(gaccMeta.default_year);
  gaccForm.month_start = String(gaccMeta.default_month_start);
  gaccForm.month_end = String(gaccMeta.default_month_end);
}

function clampGaccMonths() {
  const opts = gaccMonthOptions.value;
  if (!opts.length) return;
  const max = String(opts[opts.length - 1]);
  if (Number(gaccForm.month_start) > Number(max)) gaccForm.month_start = max;
  if (Number(gaccForm.month_end) > Number(max)) gaccForm.month_end = max;
  if (Number(gaccForm.month_end) < Number(gaccForm.month_start)) {
    gaccForm.month_end = gaccForm.month_start;
  }
}

async function onGaccQuery() {
  if (!gaccFormReady.value || gaccState.querying) return;
  gaccState.querying = true;
  gaccState.error = "";
  gaccState.job = null;
  try {
    const body = {
      flow_type: gaccForm.flow_type,
      currency: gaccForm.currency,
      year: Number(gaccForm.year),
      month_start: Number(gaccForm.month_start),
      month_end: Number(gaccForm.month_end),
      split_by_month: gaccForm.split_by_month,
      output_fields: [...gaccForm.output_fields],
    };
    const res = await fetch("/api/gacc/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `发起查询失败 (${res.status})`);
    }
    const data = await res.json();
    gaccState.jobId = data.job_id;
    gaccState.job = data.job;
    startGaccPoll();
  } catch (e) {
    gaccState.querying = false;
    gaccState.error = e.message || "发起查询失败";
  }
}

function onGaccReset() {
  gaccForm.flow_type = "import";
  gaccForm.currency = "USD";
  gaccForm.split_by_month = false;
  gaccForm.output_fields = [
    ...(gaccMeta.default_output_fields.length
      ? gaccMeta.default_output_fields
      : ["CODE_TS", "ORIGIN_COUNTRY", "TRADE_MODE", "TRADE_CO_PORT"]),
  ];
  applyGaccDefaults();
}

function onSliceSearch() {
  fetchSlices(1);
}

async function onSliceReset() {
  sliceFilters.reporter_code = "";
  sliceFilters.year = "";
  sliceFilters.freq_code = "";
  sliceFilters.status = "";
  await fetchSlices(1);
}

function goSlicePage(page) {
  if (page < 1 || page > sliceState.pages || page === sliceState.page) return;
  fetchSlices(page);
}

function onSlicePageSizeChange() {
  fetchSlices(1);
}

function fillSyncFromSlice(row) {
  syncForm.reporter_code = String(row.reporter_code);
  syncForm.year = String(row.year);
  syncForm.freq_code = row.freq_code;
  syncForm.month = row.freq_code === "M" ? String(row.month || 0) : "0";
  activeView.mode = "trade";
}

async function onSyncSlice() {
  if (!syncFormReady.value || syncState.syncing) return;
  syncState.syncing = true;
  syncState.error = "";
  syncState.result = null;
  resetSyncProgress();
  try {
    const body = {
      reporter_code: Number(syncForm.reporter_code),
      year: Number(syncForm.year),
      freq_code: syncForm.freq_code,
      month: syncForm.freq_code === "M" ? Number(syncForm.month) : 0,
      force_refresh: syncForm.force_refresh,
    };
    const data = await consumeSyncStream(body);
    await applySyncSuccess(data);
  } catch (e) {
    syncState.error = e.message || "同步失败";
  } finally {
    syncState.syncing = false;
    resetSyncProgress();
  }
}

function onSearch() {
  fetchTrade(1);
}

function parseExportFilename(contentDisposition) {
  if (!contentDisposition) return "trade_export.xlsx";
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) return decodeURIComponent(utf8Match[1]);
  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  return plainMatch ? plainMatch[1] : "trade_export.xlsx";
}

async function onExport() {
  if (exportState.exporting || state.total <= 0) return;
  exportState.exporting = true;
  exportState.error = "";
  state.error = "";
  try {
    const res = await fetch(`/api/trade/export?${buildFilterQuery()}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `导出失败 (${res.status})`);
    }
    const blob = await res.blob();
    const filename = parseExportFilename(
      res.headers.get("Content-Disposition"),
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
    if (res.headers.get("X-Export-Truncated") === "1") {
      exportState.error = `已导出前 ${res.headers.get("X-Export-Rows")} 条（共 ${res.headers.get("X-Export-Total")} 条，已达上限）`;
    }
  } catch (e) {
    exportState.error = e.message || "导出失败";
    state.error = exportState.error;
  } finally {
    exportState.exporting = false;
  }
}

function onScopeChange() {
  if (filters.partner_scope === "total") {
    filters.partner_name = "";
  }
  onSearch();
}

function onPageSizeChange() {
  fetchTrade(1);
}

async function onReset() {
  filters.reporter_code = "";
  filters.year = "";
  filters.month = "";
  filters.freq_code = "A";
  filters.flow_code = "";
  filters.partner_name = "";
  filters.partner_scope = "countries";
  state.page_size = NO_SCROLL_SIZE;
  await fetchMeta();
  fetchTrade(1);
}

function setSyncFreq(code) {
  syncForm.freq_code = code;
  if (code === "M" && !syncForm.month) {
    syncForm.month = "0";
  }
}

function setQueryFreq(code) {
  filters.freq_code = code;
  onFreqChange();
}

function goPage(page) {
  if (page < 1 || page > state.pages || page === state.page) return;
  fetchTrade(page);
}

onMounted(async () => {
  try {
    await Promise.all([fetchMeta(), fetchSyncOptions()]);
    await fetchTrade(1);
  } catch (e) {
    state.error = e.message || "初始化失败";
  }
});

onUnmounted(() => {
  stopGaccPoll();
});
</script>

<template>
  <div class="app-shell" :class="{ 'gacc-mode': activeView.mode === 'gacc' }">
    <aside v-if="activeView.mode !== 'gacc'" class="sync-sidebar">
      <template v-if="activeView.mode === 'slices'">
        <div class="sync-header">
          <h2 class="sync-title">同步缓存</h2>
          <p class="sync-subtitle">各组合同步状态汇总</p>
        </div>
        <section class="slice-summary slice-sidebar-summary">
          <div class="slice-stats">
            <span class="stat-chip">
              共 <strong>{{ sliceState.summary.total }}</strong> 条
            </span>
            <span class="stat-chip stat-chip--ok">
              有数据 <strong>{{ sliceState.summary.ok }}</strong>
            </span>
            <span class="stat-chip stat-chip--empty">
              官网暂无 <strong>{{ sliceState.summary.empty }}</strong>
            </span>
            <span class="stat-chip stat-chip--error">
              失败 <strong>{{ sliceState.summary.error }}</strong>
            </span>
          </div>
        </section>
      </template>

      <template v-else>
        <div class="sync-header">
          <h2 class="sync-title">从 UN Comtrade 同步</h2>
          <p class="sync-subtitle">国家与年份选项与官网一致（英文国名）</p>
        </div>

        <div v-if="syncMeta.loading" class="sync-loading">加载国家列表…</div>

        <template v-else>
          <div class="field">
            <label>Frequency</label>
            <div class="freq-toggle">
              <button
                type="button"
                :class="{ active: syncForm.freq_code === 'A' }"
                @click="setSyncFreq('A')"
              >
                Annual
              </button>
              <button
                type="button"
                :class="{ active: syncForm.freq_code === 'M' }"
                @click="setSyncFreq('M')"
              >
                Monthly
              </button>
            </div>
          </div>

          <ComtradeSelect
            v-model="syncForm.reporter_code"
            label="Reporters"
            :options="reporterSelectOptions"
            placeholder=""
          />

          <ComtradeSelect
            v-model="syncForm.year"
            label="Periods (year)"
            :groups="yearSelectGroups"
            placeholder=""
          />

          <ComtradeSelect
            v-if="isMonthlySync"
            v-model="syncForm.month"
            label="Periods (year, month)"
            :groups="syncMonthSelectGroups"
            placeholder=""
          />

          <label class="force-refresh">
            <input v-model="syncForm.force_refresh" type="checkbox" />
            强制刷新
          </label>

          <div
            v-if="syncState.syncing && syncState.progress.total > 0"
            class="sync-progress"
          >
            <div class="sync-progress-meta">
              <span>
                {{ syncState.progress.current }} /
                {{ syncState.progress.total }}
              </span>
              <span>{{ syncState.progress.percent }}%</span>
            </div>
            <div class="sync-progress-track">
              <div
                class="sync-progress-bar"
                :style="{ width: `${syncState.progress.percent}%` }"
              />
            </div>
            <p v-if="syncState.progress.label" class="sync-progress-label">
              {{ syncState.progress.label }}
            </p>
          </div>

          <button
            class="btn btn-sync btn-block"
            :disabled="!syncFormReady || syncState.syncing"
            @click="onSyncSlice"
          >
            {{
              syncState.syncing
                ? syncState.progress.total > 0
                  ? `同步中 ${syncState.progress.current}/${syncState.progress.total}`
                  : "同步中…"
                : "同步到本地数据库"
            }}
          </button>

          <p v-if="currentSliceHint?.status === 'empty'" class="sync-hint warn">
            已于
            {{ formatFetchedAt(currentSliceHint.fetched_at) }}
            确认：官网暂无该组合数据
          </p>
          <p v-else-if="currentSliceHint?.status === 'ok'" class="sync-hint ok">
            本地已有数据（{{ currentSliceHint.record_count }} 条<template
              v-if="currentSliceHint.month_count"
              >，{{ currentSliceHint.month_count }} 个月</template
            >， {{ formatFetchedAt(currentSliceHint.fetched_at) }}）
          </p>
          <p
            v-else-if="currentSliceHint?.status === 'error'"
            class="sync-hint warn"
          >
            上次同步失败：{{ currentSliceHint.error_message || "未知错误" }}
          </p>

          <div v-if="syncState.error" class="sync-result error">
            {{ syncState.error }}
          </div>
          <div
            v-else-if="syncState.result"
            class="sync-result"
            :class="syncState.result.status"
          >
            <template v-if="syncState.result.cached">
              {{ syncState.result.message }}（使用缓存）
            </template>
            <template v-else-if="syncState.result.status === 'ok'">
              {{ syncState.result.message }}，已写入数据库
            </template>
            <template v-else>
              {{ syncState.result.message }}
            </template>
          </div>
        </template>
      </template>
    </aside>

    <aside v-if="activeView.mode === 'gacc'" class="sync-sidebar gacc-sidebar">
      <div class="sync-header">
        <h2 class="sync-title">筛选条件设置</h2>
      </div>

      <div v-if="gaccMeta.loading" class="sync-loading">加载选项…</div>

      <template v-else>
        <section class="gacc-filters">
          <div class="field">
            <label>进出口类型</label>
            <div class="radio-row">
              <label
                v-for="f in gaccMeta.flow_types"
                :key="f.value"
                class="radio-label"
              >
                <input
                  v-model="gaccForm.flow_type"
                  type="radio"
                  :value="f.value"
                />
                {{ f.label }}
              </label>
            </div>
          </div>
          <div class="field">
            <label>币制</label>
            <div class="radio-row">
              <label
                v-for="c in gaccMeta.currencies"
                :key="c.value"
                class="radio-label"
              >
                <input
                  v-model="gaccForm.currency"
                  type="radio"
                  :value="c.value"
                />
                {{ c.label }}
              </label>
            </div>
          </div>
          <div class="field gacc-time-row">
            <label>进出口起止时间</label>
            <div class="gacc-time-inputs">
              <select
                v-model="gaccForm.year"
                class="gacc-select"
                @change="clampGaccMonths"
              >
                <option v-for="y in gaccMeta.years" :key="y" :value="String(y)">
                  {{ y }}年
                </option>
              </select>
              <select
                v-model="gaccForm.month_start"
                class="gacc-select"
                @change="clampGaccMonths"
              >
                <option
                  v-for="m in gaccMonthOptions"
                  :key="'s' + m"
                  :value="String(m)"
                >
                  {{ m }}月
                </option>
              </select>
              <span class="gacc-time-sep">到</span>
              <select
                v-model="gaccForm.month_end"
                class="gacc-select"
                @change="clampGaccMonths"
              >
                <option
                  v-for="m in gaccMonthOptions"
                  :key="'e' + m"
                  :value="String(m)"
                >
                  {{ m }}月
                </option>
              </select>
            </div>
            <p class="gacc-time-hint">
              {{ gaccMeta.latest_year }} 年数据目前发布至
              {{ gaccMeta.latest_month }} 月
            </p>
          </div>
          <label class="force-refresh">
            <input v-model="gaccForm.split_by_month" type="checkbox" />
            分月展示
          </label>
          <div class="field gacc-output-fields">
            <label>输出字段分组</label>
            <div class="gacc-output-grid">
              <div
                v-for="(slot, idx) in gaccForm.output_fields"
                :key="idx"
                class="gacc-output-row"
              >
                <span class="gacc-output-idx">第 {{ idx + 1 }} 组</span>
                <select
                  v-model="gaccForm.output_fields[idx]"
                  class="gacc-select"
                >
                  <option value="">--未选择--</option>
                  <option
                    v-for="opt in gaccMeta.output_field_options"
                    :key="opt.value"
                    :value="opt.value"
                  >
                    {{ opt.label }}
                  </option>
                </select>
              </div>
            </div>
            <p class="gacc-time-hint">
              与海关站 outerField1-4 对应，开始查询前会自动填入
            </p>
          </div>
          <div class="field actions gacc-actions">
            <button
              class="btn btn-primary btn-gacc-query btn-block"
              :disabled="!gaccFormReady || gaccState.querying"
              @click="onGaccQuery"
            >
              {{ gaccState.querying ? "采集中…" : "开始查询" }}
            </button>
            <button
              class="btn btn-ghost btn-block"
              :disabled="gaccState.querying"
              @click="onGaccReset"
            >
              重置
            </button>
          </div>
          <div
            v-if="gaccState.querying && gaccState.job"
            class="gacc-job-banner"
            :class="gaccState.job.status"
          >
            <strong>任务 {{ gaccState.job.id }}</strong>
            <span>{{ gaccState.job.message }}</span>
            <span v-if="gaccState.job.status === 'waiting_captcha'">
              {{
                gaccMeta.captcha_mode === "auto"
                  ? "正在自动处理滑块验证码…"
                  : "请在弹出窗口完成验证码"
              }}（{{ gaccMeta.captcha_timeout_sec }}s 内）
            </span>
          </div>
          <div
            v-else-if="gaccState.job?.status === 'success'"
            class="gacc-job-banner success"
          >
            <strong>任务 {{ gaccState.job.id }} 完成</strong>
            <span>{{ gaccState.job.message }}</span>
            <span v-if="gaccState.job.csv_path" class="gacc-csv-path">
              原始 CSV：{{ gaccState.job.csv_path }}
            </span>
          </div>
          <div
            v-else-if="gaccState.job?.status === 'error'"
            class="gacc-job-banner error"
          >
            <strong>任务 {{ gaccState.job.id }} 失败</strong>
            <span>{{ gaccState.job.error_message }}</span>
          </div>
        </section>
      </template>
    </aside>

    <div class="main-column">
      <header class="header">
        <div class="header-row">
          <div>
            <h1 class="page-title">各国贸易数据</h1>
            <p class="page-subtitle">
              {{
                activeView.mode === "trade"
                  ? "本地缓存查询 · 右侧按需从官网同步"
                  : activeView.mode === "gacc"
                    ? "本地入库数据 · 右侧发起查询"
                    : "查看已同步/已缓存的组合，避免重复请求 Comtrade"
              }}
            </p>
          </div>
          <nav class="view-tabs">
            <button
              type="button"
              class="view-tab"
              :class="{ active: activeView.mode === 'trade' }"
              @click="switchView('trade')"
            >
              数据查询
            </button>
            <button
              type="button"
              class="view-tab"
              :class="{ active: activeView.mode === 'slices' }"
              @click="switchView('slices')"
            >
              同步缓存
            </button>
            <button
              type="button"
              class="view-tab"
              :class="{ active: activeView.mode === 'gacc' }"
              @click="switchView('gacc')"
            >
              中国海关在线查询
            </button>
          </nav>
        </div>
      </header>

      <div
        v-if="activeView.mode === 'trade' && state.error"
        class="panel-error"
      >
        {{ state.error }}
      </div>
      <div
        v-if="activeView.mode === 'slices' && sliceState.error"
        class="panel-error"
      >
        {{ sliceState.error }}
      </div>
      <div
        v-if="activeView.mode === 'gacc' && gaccState.error"
        class="panel-error"
      >
        {{ gaccState.error }}
      </div>

      <template v-if="activeView.mode === 'trade'">
        <section class="filters">
          <div class="field field-freq">
            <label>频率</label>
            <div class="freq-toggle">
              <button
                type="button"
                :class="{ active: filters.freq_code === 'A' }"
                @click="setQueryFreq('A')"
              >
                年度
              </button>
              <button
                type="button"
                :class="{ active: filters.freq_code === 'M' }"
                @click="setQueryFreq('M')"
              >
                月度
              </button>
            </div>
          </div>

          <div class="field">
            <label>报告国</label>
            <select v-model="filters.reporter_code" @change="onReporterChange">
              <option value="">全部</option>
              <option v-for="r in meta.reporters" :key="r.code" :value="r.code">
                {{ r.label }}
              </option>
            </select>
          </div>

          <div class="field">
            <label>年份</label>
            <select v-model="filters.year" @change="onYearChange">
              <option value="">全部</option>
              <option v-for="y in meta.years" :key="y" :value="y">
                {{ y }}
              </option>
            </select>
          </div>

          <div v-if="isMonthlyQuery" class="field field-month">
            <label>月份</label>
            <select v-model="filters.month" @change="onMonthChange">
              <option value="">全部</option>
              <option
                v-for="m in meta.months.filter((m) => m.value !== 0)"
                :key="m.value"
                :value="m.value"
              >
                {{ m.period_label || m.label }}
              </option>
            </select>
          </div>

          <div class="field">
            <label>贸易流向</label>
            <select v-model="filters.flow_code">
              <option value="">全部</option>
              <option v-for="f in meta.flows" :key="f.code" :value="f.code">
                {{ f.label }}
              </option>
            </select>
          </div>

          <div class="field">
            <label>统计范围</label>
            <select v-model="filters.partner_scope" @change="onScopeChange">
              <option value="countries">具体国家</option>
              <option value="total">总计</option>
            </select>
          </div>

          <div class="field field-wide">
            <label>伙伴国名称</label>
            <input
              v-model="filters.partner_name"
              type="text"
              placeholder="如 China、Germany"
              :disabled="filters.partner_scope === 'total'"
              @keyup.enter="onSearch"
            />
          </div>

          <div class="field actions">
            <button class="btn btn-primary" @click="onSearch">查询</button>
            <button
              class="btn btn-export"
              :disabled="
                state.total <= 0 || exportState.exporting || state.loading
              "
              @click="onExport"
            >
              {{ exportState.exporting ? "导出中…" : "导出 xlsx" }}
            </button>
            <button class="btn btn-ghost" @click="onReset">重置</button>
          </div>
        </section>

        <section class="main-panel">
          <div v-if="!state.items.length && !state.loading" class="panel-empty">
            <template v-if="!meta.years.length">
              本地暂无数据，请先从左侧从 UN Comtrade 同步
            </template>
            <template v-else>
              当前筛选条件下暂无数据。若需新国家/年份，请从左侧同步区拉取
            </template>
          </div>

          <div
            v-else
            class="table-scroll"
            :class="{
              'is-loading': state.loading,
              scrollable: tableScrollable,
            }"
            :style="tableStyle"
          >
            <table :class="{ 'mode-total': isTotalScope }">
              <colgroup>
                <col class="col-reporter" />
                <col class="col-year" />
                <col v-if="isMonthlyQuery" class="col-month" />
                <col class="col-flow" />
                <template v-if="!isTotalScope">
                  <col class="col-partner" />
                  <col class="col-code" />
                </template>
                <col class="col-amount" />
              </colgroup>
              <thead>
                <tr>
                  <th>报告国</th>
                  <th>年份</th>
                  <th v-if="isMonthlyQuery">月份</th>
                  <th>流向</th>
                  <th v-if="!isTotalScope">伙伴国</th>
                  <th v-if="!isTotalScope">伙伴代码</th>
                  <th>贸易额 (USD)</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in state.items" :key="row.id">
                  <td>{{ row.reporter_label }}</td>
                  <td>{{ row.year }}</td>
                  <td v-if="isMonthlyQuery">{{ row.month_label }}</td>
                  <td>{{ row.flow_label }}</td>
                  <td v-if="!isTotalScope">{{ row.partner_name || "—" }}</td>
                  <td v-if="!isTotalScope">{{ row.partner_code }}</td>
                  <td class="amount">{{ formatUsd(row.trade_value_usd) }}</td>
                </tr>
                <tr
                  v-for="n in paddingCount"
                  :key="'pad-' + n"
                  class="row-pad"
                  aria-hidden="true"
                >
                  <td>&nbsp;</td>
                  <td>&nbsp;</td>
                  <td v-if="isMonthlyQuery">&nbsp;</td>
                  <td>&nbsp;</td>
                  <td v-if="!isTotalScope">&nbsp;</td>
                  <td v-if="!isTotalScope">&nbsp;</td>
                  <td>&nbsp;</td>
                </tr>
              </tbody>
            </table>
            <div v-if="state.loading" class="table-overlay">加载中…</div>
          </div>

          <div v-if="state.total > 0" class="pagination">
            <div class="pagination-left">
              <span>共 {{ state.total }} 条</span>
              <label class="page-size-label">
                每页
                <select
                  v-model.number="state.page_size"
                  class="page-size-select"
                  @change="onPageSizeChange"
                >
                  <option v-for="n in PAGE_SIZE_OPTIONS" :key="n" :value="n">
                    {{ n }}
                  </option>
                </select>
                条
              </label>
            </div>

            <div class="pagination-center">
              <button
                class="page-btn"
                :disabled="state.page <= 1 || state.loading"
                @click="goPage(1)"
              >
                首页
              </button>
              <button
                class="page-btn"
                :disabled="state.page <= 1 || state.loading"
                @click="goPage(state.page - 1)"
              >
                上一页
              </button>
              <template v-for="(p, idx) in visiblePages" :key="idx">
                <span v-if="p === '...'" class="page-ellipsis">…</span>
                <button
                  v-else
                  class="page-btn"
                  :class="{ active: p === state.page }"
                  :disabled="state.loading"
                  @click="goPage(p)"
                >
                  {{ p }}
                </button>
              </template>
              <button
                class="page-btn"
                :disabled="state.page >= state.pages || state.loading"
                @click="goPage(state.page + 1)"
              >
                下一页
              </button>
              <button
                class="page-btn"
                :disabled="state.page >= state.pages || state.loading"
                @click="goPage(state.pages)"
              >
                末页
              </button>
            </div>

            <div class="pagination-right">
              第 {{ state.page }} / {{ state.pages }} 页
            </div>
          </div>
        </section>
      </template>

      <template v-else-if="activeView.mode === 'slices'">
        <p class="slice-hint">
          每一行代表一次同步记录（国家 + 周期 +
          进出口）。有数据的不会重复拉取；官网暂无的会负缓存
          {{ sliceMeta.empty_ttl_days }} 天，避免浪费 API 配额。
        </p>

        <section class="filters slice-filters">
          <div class="field">
            <label>报告国</label>
            <select v-model="sliceFilters.reporter_code">
              <option value="">全部</option>
              <option
                v-for="r in sliceMeta.reporters"
                :key="r.code"
                :value="r.code"
              >
                {{ r.label }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>年份</label>
            <select v-model="sliceFilters.year">
              <option value="">全部</option>
              <option v-for="y in sliceMeta.years" :key="y" :value="y">
                {{ y }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>频率</label>
            <select v-model="sliceFilters.freq_code">
              <option value="">全部</option>
              <option
                v-for="f in sliceMeta.frequencies"
                :key="f.code"
                :value="f.code"
              >
                {{ f.label }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>状态</label>
            <select v-model="sliceFilters.status">
              <option value="">全部</option>
              <option
                v-for="s in sliceMeta.statuses"
                :key="s.code"
                :value="s.code"
              >
                {{ s.label }}
              </option>
            </select>
          </div>
          <div class="field actions">
            <button class="btn btn-primary" @click="onSliceSearch">查询</button>
            <button class="btn btn-ghost" @click="onSliceReset">重置</button>
          </div>
        </section>

        <section class="main-panel">
          <div
            v-if="!sliceState.items.length && !sliceState.loading"
            class="panel-empty"
          >
            暂无同步记录，请先从左侧拉取数据
          </div>
          <div
            v-else
            class="table-scroll slice-table-wrap"
            :class="{ 'is-loading': sliceState.loading }"
          >
            <table class="slice-table">
              <thead>
                <tr>
                  <th>报告国</th>
                  <th>周期</th>
                  <th>流向</th>
                  <th>记录数</th>
                  <th>同步时间</th>
                  <th>缓存说明</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in sliceState.items"
                  :key="`${row.reporter_code}-${row.year}-${row.month}-${row.flow_code}-${row.freq_code}`"
                >
                  <td>{{ row.reporter_label }}</td>
                  <td>
                    {{ row.period_label }}
                    <span class="slice-freq-tag">{{ row.freq_label }}</span>
                  </td>
                  <td>{{ row.flow_label }}</td>
                  <td>{{ row.record_count }}</td>
                  <td>{{ formatFetchedAt(row.fetched_at) }}</td>
                  <td class="cache-cell">
                    <span
                      class="status-badge"
                      :class="`status-badge--${row.status}`"
                    >
                      {{ row.status_label }}
                    </span>
                    <span class="cache-note">{{ row.cache_note }}</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      class="btn-link"
                      @click="fillSyncFromSlice(row)"
                    >
                      去同步
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="sliceState.loading" class="table-overlay">加载中…</div>
          </div>

          <div v-if="sliceState.total > 0" class="pagination">
            <div class="pagination-left">
              <span>共 {{ sliceState.total }} 条</span>
              <label class="page-size-label">
                每页
                <select
                  v-model.number="sliceState.page_size"
                  class="page-size-select"
                  @change="onSlicePageSizeChange"
                >
                  <option v-for="n in PAGE_SIZE_OPTIONS" :key="n" :value="n">
                    {{ n }}
                  </option>
                </select>
                条
              </label>
            </div>
            <div class="pagination-center">
              <button
                class="page-btn"
                :disabled="sliceState.page <= 1 || sliceState.loading"
                @click="goSlicePage(1)"
              >
                首页
              </button>
              <button
                class="page-btn"
                :disabled="sliceState.page <= 1 || sliceState.loading"
                @click="goSlicePage(sliceState.page - 1)"
              >
                上一页
              </button>
              <template v-for="(p, idx) in sliceVisiblePages" :key="idx">
                <span v-if="p === '...'" class="page-ellipsis">…</span>
                <button
                  v-else
                  class="page-btn"
                  :class="{ active: p === sliceState.page }"
                  :disabled="sliceState.loading"
                  @click="goSlicePage(p)"
                >
                  {{ p }}
                </button>
              </template>
              <button
                class="page-btn"
                :disabled="
                  sliceState.page >= sliceState.pages || sliceState.loading
                "
                @click="goSlicePage(sliceState.page + 1)"
              >
                下一页
              </button>
              <button
                class="page-btn"
                :disabled="
                  sliceState.page >= sliceState.pages || sliceState.loading
                "
                @click="goSlicePage(sliceState.pages)"
              >
                末页
              </button>
            </div>
            <div class="pagination-right">
              第 {{ sliceState.page }} / {{ sliceState.pages }} 页
            </div>
          </div>
        </section>
      </template>

      <template v-else-if="activeView.mode === 'gacc'">
        <section class="gacc-browse-filters">
          <div class="field">
            <label>进出口类型</label>
            <select v-model="gaccBrowseFilters.flow_type" class="gacc-select">
              <option value="">全部</option>
              <option
                v-for="f in gaccMeta.flow_types"
                :key="f.value"
                :value="f.value"
              >
                {{ f.label }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>币制</label>
            <select v-model="gaccBrowseFilters.currency" class="gacc-select">
              <option value="">全部</option>
              <option
                v-for="c in gaccMeta.currencies"
                :key="c.value"
                :value="c.value"
              >
                {{ c.label }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>年份</label>
            <select v-model="gaccBrowseFilters.year" class="gacc-select">
              <option value="">全部</option>
              <option v-for="y in gaccMeta.years" :key="y" :value="String(y)">
                {{ y }}年
              </option>
            </select>
          </div>
          <div class="field">
            <label>月份</label>
            <select v-model="gaccBrowseFilters.month" class="gacc-select">
              <option value="">全部</option>
              <option
                v-for="m in gaccBrowseMonthOptions"
                :key="m"
                :value="String(m)"
              >
                {{ m }}月
              </option>
            </select>
          </div>
          <div class="field actions gacc-browse-actions">
            <button class="btn btn-primary" @click="onGaccBrowseSearch">
              筛选
            </button>
            <button class="btn btn-ghost" @click="onGaccBrowseReset">
              重置
            </button>
          </div>
        </section>

        <section class="main-panel gacc-data-panel">
          <div
            v-if="!gaccBrowseState.items.length && !gaccBrowseState.loading"
            class="panel-empty"
          >
            暂无数据。右侧设置条件发起查询，入库后将在此展示
          </div>
          <template v-else>
            <div
              class="gacc-table-scroll"
              :class="{ 'is-loading': gaccBrowseState.loading }"
            >
              <table class="gacc-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>进出口</th>
                    <th>币制</th>
                    <th>商品编码</th>
                    <th>商品名称</th>
                    <th>贸易伙伴编码</th>
                    <th>贸易伙伴名称</th>
                    <th>贸易方式编码</th>
                    <th>贸易方式名称</th>
                    <th>注册地编码</th>
                    <th>注册地名称</th>
                    <th>第一数量</th>
                    <th>第一计量单位</th>
                    <th>第二数量</th>
                    <th>第二计量单位</th>
                    <th class="num">{{ gaccValueColumnLabel }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in gaccBrowseState.items" :key="row.id">
                    <td class="gacc-period">{{ row.period_label || "—" }}</td>
                    <td>{{ row.flow_label || "—" }}</td>
                    <td>{{ row.currency_label || "—" }}</td>
                    <td class="mono">{{ row.hs_code || "—" }}</td>
                    <td class="gacc-name">{{ row.hs_name || "—" }}</td>
                    <td class="mono">{{ row.partner_code || "—" }}</td>
                    <td>{{ row.partner_name || "—" }}</td>
                    <td class="mono">{{ row.trade_mode_code || "—" }}</td>
                    <td>{{ row.trade_mode_name || "—" }}</td>
                    <td class="mono">{{ row.reg_place_code || "—" }}</td>
                    <td>{{ row.reg_place_name || "—" }}</td>
                    <td class="num">{{ formatGaccNum(row.qty1) }}</td>
                    <td>{{ row.unit1 || "—" }}</td>
                    <td class="num">
                      {{ showGaccQty2(row) ? formatGaccNum(row.qty2) : "—" }}
                    </td>
                    <td>{{ showGaccQty2(row) ? row.unit2 || "—" : "—" }}</td>
                    <td class="num gacc-value">
                      {{ formatGaccNum(row.value) }}
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-if="gaccBrowseState.loading" class="table-overlay">
                加载中…
              </div>
            </div>

            <div
              v-if="gaccBrowseState.total > 0"
              class="pagination gacc-pagination"
            >
              <div class="pagination-left">
                <span>共 {{ gaccBrowseState.total }} 条</span>
                <label class="page-size-label">
                  每页
                  <select
                    v-model.number="gaccBrowseState.page_size"
                    class="page-size-select"
                    @change="onGaccBrowsePageSizeChange"
                  >
                    <option v-for="n in PAGE_SIZE_OPTIONS" :key="n" :value="n">
                      {{ n }}
                    </option>
                  </select>
                  条
                </label>
              </div>
              <div class="pagination-center">
                <button
                  class="page-btn"
                  :disabled="
                    gaccBrowseState.page <= 1 || gaccBrowseState.loading
                  "
                  @click="goGaccBrowsePage(1)"
                >
                  首页
                </button>
                <button
                  class="page-btn"
                  :disabled="
                    gaccBrowseState.page <= 1 || gaccBrowseState.loading
                  "
                  @click="goGaccBrowsePage(gaccBrowseState.page - 1)"
                >
                  上一页
                </button>
                <template v-for="(p, idx) in gaccVisiblePages" :key="idx">
                  <span v-if="p === '...'" class="page-ellipsis">…</span>
                  <button
                    v-else
                    class="page-btn"
                    :class="{ active: p === gaccBrowseState.page }"
                    :disabled="gaccBrowseState.loading"
                    @click="goGaccBrowsePage(p)"
                  >
                    {{ p }}
                  </button>
                </template>
                <button
                  class="page-btn"
                  :disabled="
                    gaccBrowseState.page >= gaccBrowseState.pages ||
                    gaccBrowseState.loading
                  "
                  @click="goGaccBrowsePage(gaccBrowseState.page + 1)"
                >
                  下一页
                </button>
                <button
                  class="page-btn"
                  :disabled="
                    gaccBrowseState.page >= gaccBrowseState.pages ||
                    gaccBrowseState.loading
                  "
                  @click="goGaccBrowsePage(gaccBrowseState.pages)"
                >
                  末页
                </button>
              </div>
              <div class="pagination-right">
                第 {{ gaccBrowseState.page }} / {{ gaccBrowseState.pages }} 页
              </div>
            </div>
          </template>
        </section>
      </template>
    </div>
  </div>
</template>
