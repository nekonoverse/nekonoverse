import { createSignal, onMount, Show, For } from "solid-js";
import { useI18n } from "../i18n";
import { currentUser } from "../stores/auth";
import {
  getAdminStats, getServerSettings, updateServerSettings,
  getAdminUsers, changeUserRole, suspendUser, unsuspendUser, silenceUser, unsilenceUser,
  getDomainBlocks, createDomainBlock, removeDomainBlock,
  getReports, resolveReport, rejectReport,
  getModerationLog, uploadServerIcon, markNoteSensitive,
  type AdminStats, type ServerSettings, type AdminUser,
  type DomainBlock, type Report, type ModerationLogEntry,
} from "../api/admin";

type Tab = "overview" | "settings" | "users" | "domains" | "reports" | "log";

export default function Admin() {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = createSignal<Tab>("overview");

  const isStaff = () => {
    const u = currentUser();
    return u && (u.role === "admin" || u.role === "moderator");
  };

  const isAdmin = () => currentUser()?.role === "admin";

  return (
    <div class="page-container admin-page">
      <h1>{t("admin.title")}</h1>
      <Show when={isStaff()} fallback={<p class="error">{t("admin.noAccess")}</p>}>
        <div class="settings-tabs">
          {([
            { key: "overview" as Tab, label: t("admin.tabOverview") },
            ...(isAdmin() ? [{ key: "settings" as Tab, label: t("admin.tabSettings") }] : []),
            { key: "users" as Tab, label: t("admin.tabUsers") },
            { key: "domains" as Tab, label: t("admin.tabDomains") },
            { key: "reports" as Tab, label: t("admin.tabReports") },
            { key: "log" as Tab, label: t("admin.tabLog") },
          ]).map((tab) => (
            <button
              class={`settings-tab${activeTab() === tab.key ? " settings-tab-active" : ""}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <Show when={activeTab() === "overview"}><OverviewTab /></Show>
        <Show when={activeTab() === "settings"}><ServerSettingsTab /></Show>
        <Show when={activeTab() === "users"}><UsersTab /></Show>
        <Show when={activeTab() === "domains"}><DomainsTab /></Show>
        <Show when={activeTab() === "reports"}><ReportsTab /></Show>
        <Show when={activeTab() === "log"}><LogTab /></Show>
      </Show>
    </div>
  );
}

function OverviewTab() {
  const { t } = useI18n();
  const [stats, setStats] = createSignal<AdminStats | null>(null);

  onMount(async () => {
    try { setStats(await getAdminStats()); } catch {}
  });

  return (
    <div class="settings-section">
      <h3>{t("admin.tabOverview")}</h3>
      <Show when={stats()} fallback={<p>{t("common.loading")}</p>}>
        {(s) => (
          <div class="admin-stats">
            <div class="admin-stat-card">
              <span class="admin-stat-num">{s().user_count}</span>
              <span class="admin-stat-label">{t("admin.users")}</span>
            </div>
            <div class="admin-stat-card">
              <span class="admin-stat-num">{s().note_count}</span>
              <span class="admin-stat-label">{t("admin.notes")}</span>
            </div>
            <div class="admin-stat-card">
              <span class="admin-stat-num">{s().domain_count}</span>
              <span class="admin-stat-label">{t("admin.domains")}</span>
            </div>
          </div>
        )}
      </Show>
    </div>
  );
}

function ServerSettingsTab() {
  const { t } = useI18n();
  const [settings, setSettings] = createSignal<ServerSettings | null>(null);
  const [saving, setSaving] = createSignal(false);
  const [saved, setSaved] = createSignal(false);
  const [name, setName] = createSignal("");
  const [desc, setDesc] = createSignal("");
  const [tos, setTos] = createSignal("");
  const [regOpen, setRegOpen] = createSignal(true);
  const [iconUrl, setIconUrl] = createSignal("");
  const [uploadingIcon, setUploadingIcon] = createSignal(false);
  let iconInput!: HTMLInputElement;

  onMount(async () => {
    try {
      const s = await getServerSettings();
      setSettings(s);
      setName(s.server_name || "");
      setDesc(s.server_description || "");
      setTos(s.tos_url || "");
      setRegOpen(s.registration_open);
      if (s.server_icon_url) setIconUrl(s.server_icon_url);
    } catch {}
  });

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const updated = await updateServerSettings({
        server_name: name() || null,
        server_description: desc() || null,
        tos_url: tos() || null,
        registration_open: regOpen(),
      });
      setSettings(updated);
      setSaved(true);
    } catch {}
    setSaving(false);
  };

  return (
    <Show when={settings()} fallback={<p>{t("common.loading")}</p>}>
      <div class="settings-section">
        <h3>{t("admin.serverSettings")}</h3>
        <Show when={saved()}><p class="settings-success">{t("settings.saved")}</p></Show>
        <div class="settings-form-group">
          <label>{t("admin.serverName")}</label>
          <input type="text" value={name()} onInput={(e) => setName(e.currentTarget.value)} />
        </div>
        <div class="settings-form-group">
          <label>{t("admin.serverDesc")}</label>
          <textarea rows={3} value={desc()} onInput={(e) => setDesc(e.currentTarget.value)} />
        </div>
        <div class="settings-form-group">
          <label>{t("admin.tosUrl")}</label>
          <input type="text" value={tos()} onInput={(e) => setTos(e.currentTarget.value)} />
        </div>
        <label class="toggle-label">
          <input type="checkbox" checked={regOpen()} onChange={(e) => setRegOpen(e.currentTarget.checked)} />
          {t("admin.registrationOpen")}
        </label>
        <button class="btn btn-small" onClick={handleSave} disabled={saving()}>
          {saving() ? t("profile.saving") : t("settings.save")}
        </button>
      </div>

      <div class="settings-section">
        <h3>{t("admin.serverIcon")}</h3>
        <Show when={iconUrl()}>
          <img src={iconUrl()} alt="Server icon" class="admin-server-icon-preview" />
        </Show>
        <button
          class="btn btn-small"
          onClick={() => iconInput.click()}
          disabled={uploadingIcon()}
        >
          {uploadingIcon() ? t("common.loading") : t("admin.uploadIcon")}
        </button>
        <input
          ref={iconInput}
          type="file"
          accept="image/jpeg,image/png,image/gif,image/webp,image/svg+xml"
          style="display: none"
          onChange={async (e) => {
            const file = (e.currentTarget as HTMLInputElement).files?.[0];
            if (!file) return;
            setUploadingIcon(true);
            try {
              const res = await uploadServerIcon(file);
              setIconUrl(res.url);
            } catch {}
            setUploadingIcon(false);
            (e.currentTarget as HTMLInputElement).value = "";
          }}
        />
      </div>
    </Show>
  );
}

function SensitiveMarker() {
  const { t } = useI18n();
  const [noteId, setNoteId] = createSignal("");
  const [marking, setMarking] = createSignal(false);
  const [marked, setMarked] = createSignal(false);

  const handleMark = async () => {
    if (!noteId().trim()) return;
    setMarking(true);
    setMarked(false);
    try {
      await markNoteSensitive(noteId());
      setMarked(true);
      setNoteId("");
    } catch {}
    setMarking(false);
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.markSensitive")}</h3>
      <Show when={marked()}><p class="settings-success">{t("admin.markedSensitive")}</p></Show>
      <div class="admin-domain-form">
        <input
          type="text"
          placeholder={t("admin.noteIdPlaceholder")}
          value={noteId()}
          onInput={(e) => setNoteId(e.currentTarget.value)}
        />
        <button class="btn btn-small" onClick={handleMark} disabled={marking() || !noteId().trim()}>
          {t("admin.markSensitive")}
        </button>
      </div>
    </div>
  );
}

function UsersTab() {
  const { t } = useI18n();
  const [users, setUsers] = createSignal<AdminUser[]>([]);
  const [loading, setLoading] = createSignal(true);
  const isAdmin = () => currentUser()?.role === "admin";

  onMount(async () => {
    try { setUsers(await getAdminUsers()); } catch {}
    setLoading(false);
  });

  const reload = async () => {
    try { setUsers(await getAdminUsers()); } catch {}
  };

  const handleRoleChange = async (userId: string, role: string) => {
    try { await changeUserRole(userId, role); await reload(); } catch {}
  };

  const handleSuspend = async (userId: string) => {
    if (!confirm(t("admin.confirmSuspend"))) return;
    try { await suspendUser(userId); await reload(); } catch {}
  };

  const handleUnsuspend = async (userId: string) => {
    try { await unsuspendUser(userId); await reload(); } catch {}
  };

  const handleSilence = async (userId: string) => {
    if (!confirm(t("admin.confirmSilence"))) return;
    try { await silenceUser(userId); await reload(); } catch {}
  };

  const handleUnsilence = async (userId: string) => {
    try { await unsilenceUser(userId); await reload(); } catch {}
  };

  return (
    <>
      <div class="settings-section">
        <h3>{t("admin.tabUsers")}</h3>
        <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
          <div class="admin-user-list">
            <For each={users()}>
              {(u) => (
                <div class={`admin-user-item${u.suspended ? " suspended" : ""}${u.silenced ? " silenced" : ""}`}>
                  <div class="admin-user-info">
                    <strong>{u.display_name || u.username}</strong>
                    <span class="admin-user-handle">@{u.username}</span>
                    <span class={`admin-role-badge role-${u.role}`}>{u.role}</span>
                    <Show when={u.suspended}><span class="admin-status-badge suspended">{t("admin.suspended")}</span></Show>
                    <Show when={u.silenced}><span class="admin-status-badge silenced">{t("admin.silenced")}</span></Show>
                  </div>
                  <div class="admin-user-actions">
                    <Show when={isAdmin()}>
                      <select
                        value={u.role}
                        onChange={(e) => handleRoleChange(u.id, e.currentTarget.value)}
                      >
                        <option value="user">user</option>
                        <option value="moderator">moderator</option>
                        <option value="admin">admin</option>
                      </select>
                    </Show>
                    <Show when={!u.suspended}>
                      <button class="btn btn-small btn-danger" onClick={() => handleSuspend(u.id)}>
                        {t("admin.suspend")}
                      </button>
                    </Show>
                    <Show when={u.suspended}>
                      <button class="btn btn-small" onClick={() => handleUnsuspend(u.id)}>
                        {t("admin.unsuspend")}
                      </button>
                    </Show>
                    <Show when={!u.silenced}>
                      <button class="btn btn-small" onClick={() => handleSilence(u.id)}>
                        {t("admin.silence")}
                      </button>
                    </Show>
                    <Show when={u.silenced}>
                      <button class="btn btn-small" onClick={() => handleUnsilence(u.id)}>
                        {t("admin.unsilence")}
                      </button>
                    </Show>
                  </div>
                </div>
              )}
            </For>
          </div>
        </Show>
      </div>
      <SensitiveMarker />
    </>
  );
}

function DomainsTab() {
  const { t } = useI18n();
  const [blocks, setBlocks] = createSignal<DomainBlock[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [newDomain, setNewDomain] = createSignal("");
  const [newSeverity, setNewSeverity] = createSignal("suspend");
  const [newReason, setNewReason] = createSignal("");

  onMount(async () => {
    try { setBlocks(await getDomainBlocks()); } catch {}
    setLoading(false);
  });

  const handleAdd = async () => {
    if (!newDomain()) return;
    try {
      const block = await createDomainBlock(newDomain(), newSeverity(), newReason() || undefined);
      setBlocks((prev) => [block, ...prev]);
      setNewDomain("");
      setNewReason("");
    } catch {}
  };

  const handleRemove = async (domain: string) => {
    if (!confirm(t("admin.confirmRemoveDomain"))) return;
    try {
      await removeDomainBlock(domain);
      setBlocks((prev) => prev.filter((b) => b.domain !== domain));
    } catch {}
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabDomains")}</h3>
      <div class="admin-domain-form">
        <input
          type="text"
          placeholder={t("admin.domainPlaceholder")}
          value={newDomain()}
          onInput={(e) => setNewDomain(e.currentTarget.value)}
        />
        <select value={newSeverity()} onChange={(e) => setNewSeverity(e.currentTarget.value)}>
          <option value="suspend">{t("admin.suspend")}</option>
          <option value="silence">{t("admin.silence")}</option>
        </select>
        <input
          type="text"
          placeholder={t("admin.reasonPlaceholder")}
          value={newReason()}
          onInput={(e) => setNewReason(e.currentTarget.value)}
        />
        <button class="btn btn-small" onClick={handleAdd}>{t("admin.addDomainBlock")}</button>
      </div>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={blocks().length > 0} fallback={<p class="empty">{t("admin.noDomainBlocks")}</p>}>
          <div class="admin-domain-list">
            <For each={blocks()}>
              {(b) => (
                <div class="admin-domain-item">
                  <div>
                    <strong>{b.domain}</strong>
                    <span class={`admin-severity-badge ${b.severity}`}>{b.severity}</span>
                    <Show when={b.reason}><span class="admin-domain-reason">{b.reason}</span></Show>
                  </div>
                  <button class="btn btn-small btn-danger" onClick={() => handleRemove(b.domain)}>
                    {t("admin.remove")}
                  </button>
                </div>
              )}
            </For>
          </div>
        </Show>
      </Show>
    </div>
  );
}

function ReportsTab() {
  const { t } = useI18n();
  const [reports, setReports] = createSignal<Report[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [filter, setFilter] = createSignal<string | undefined>(undefined);

  const load = async () => {
    setLoading(true);
    try { setReports(await getReports(filter())); } catch {}
    setLoading(false);
  };

  onMount(load);

  const handleResolve = async (id: string) => {
    try { await resolveReport(id); await load(); } catch {}
  };

  const handleReject = async (id: string) => {
    try { await rejectReport(id); await load(); } catch {}
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabReports")}</h3>
      <div class="admin-report-filter">
        <button class={`btn btn-small${!filter() ? " btn-active" : ""}`} onClick={() => { setFilter(undefined); load(); }}>
          {t("admin.allReports")}
        </button>
        <button class={`btn btn-small${filter() === "open" ? " btn-active" : ""}`} onClick={() => { setFilter("open"); load(); }}>
          {t("admin.openReports")}
        </button>
      </div>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={reports().length > 0} fallback={<p class="empty">{t("admin.noReports")}</p>}>
          <div class="admin-report-list">
            <For each={reports()}>
              {(r) => (
                <div class={`admin-report-item status-${r.status}`}>
                  <div class="admin-report-info">
                    <div>
                      <strong>{r.reporter}</strong> → <strong>{r.target}</strong>
                    </div>
                    <Show when={r.comment}><p class="admin-report-comment">{r.comment}</p></Show>
                    <span class="admin-report-time">{new Date(r.created_at).toLocaleString()}</span>
                    <span class={`admin-status-badge ${r.status}`}>{r.status}</span>
                  </div>
                  <Show when={r.status === "open"}>
                    <div class="admin-report-actions">
                      <button class="btn btn-small" onClick={() => handleResolve(r.id)}>{t("admin.resolve")}</button>
                      <button class="btn btn-small" onClick={() => handleReject(r.id)}>{t("admin.reject")}</button>
                    </div>
                  </Show>
                </div>
              )}
            </For>
          </div>
        </Show>
      </Show>
    </div>
  );
}

function LogTab() {
  const { t } = useI18n();
  const [entries, setEntries] = createSignal<ModerationLogEntry[]>([]);
  const [loading, setLoading] = createSignal(true);

  onMount(async () => {
    try { setEntries(await getModerationLog()); } catch {}
    setLoading(false);
  });

  return (
    <div class="settings-section">
      <h3>{t("admin.tabLog")}</h3>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={entries().length > 0} fallback={<p class="empty">{t("admin.noLogs")}</p>}>
          <div class="admin-log-list">
            <For each={entries()}>
              {(e) => (
                <div class="admin-log-item">
                  <span class="admin-log-time">{new Date(e.created_at).toLocaleString()}</span>
                  <strong>{e.moderator}</strong>
                  <span class="admin-log-action">{e.action}</span>
                  <span class="admin-log-target">{e.target_type}:{e.target_id}</span>
                  <Show when={e.reason}><span class="admin-log-reason">({e.reason})</span></Show>
                </div>
              )}
            </For>
          </div>
        </Show>
      </Show>
    </div>
  );
}
