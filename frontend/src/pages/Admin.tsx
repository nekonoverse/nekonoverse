import { createSignal, onMount, Show, For } from "solid-js";
import { useI18n } from "../i18n";
import { currentUser } from "../stores/auth";
import {
  getAdminStats, getServerSettings, updateServerSettings,
  getAdminUsers, changeUserRole, suspendUser, unsuspendUser, silenceUser, unsilenceUser,
  getDomainBlocks, createDomainBlock, removeDomainBlock,
  getReports, resolveReport, rejectReport,
  getModerationLog, uploadServerIcon, markNoteSensitive,
  getAdminEmojis, addEmoji, deleteEmoji, importEmojis, getEmojiExportUrl,
  getRemoteEmojis, getRemoteEmojiDomains, importRemoteEmoji,
  getServerFiles, uploadServerFile, deleteServerFile,
  getInviteCodes, createInviteCode, revokeInviteCode,
  type AdminStats, type ServerSettings, type AdminUser,
  type DomainBlock, type Report, type ModerationLogEntry,
  type AdminEmoji, type RemoteEmoji, type ServerFile,
  type InviteCode,
} from "../api/admin";

type Tab = "overview" | "settings" | "users" | "domains" | "reports" | "log" | "emoji" | "files" | "invites";

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
            ...(isAdmin() ? [
              { key: "emoji" as Tab, label: t("admin.tabEmoji") },
              { key: "files" as Tab, label: t("admin.tabFiles") },
              { key: "invites" as Tab, label: t("admin.tabInvites") },
            ] : []),
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
        <Show when={activeTab() === "emoji"}><EmojiTab /></Show>
        <Show when={activeTab() === "files"}><ServerFilesTab /></Show>
        <Show when={activeTab() === "invites"}><InvitesTab /></Show>
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
  const [regMode, setRegMode] = createSignal("open");
  const [inviteRole, setInviteRole] = createSignal("admin");
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
      setRegMode(s.registration_mode || "open");
      setInviteRole(s.invite_create_role || "admin");
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
        registration_mode: regMode(),
        invite_create_role: inviteRole(),
      } as Partial<ServerSettings>);
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
        <div class="settings-form-group">
          <label>{t("admin.registrationMode")}</label>
          <select value={regMode()} onChange={(e) => setRegMode(e.currentTarget.value)}>
            <option value="open">{t("admin.regModeOpen")}</option>
            <option value="invite">{t("admin.regModeInvite")}</option>
            <option value="closed">{t("admin.regModeClosed")}</option>
          </select>
        </div>
        <Show when={regMode() === "invite"}>
          <div class="settings-form-group">
            <label>{t("admin.inviteCreateRole")}</label>
            <select value={inviteRole()} onChange={(e) => setInviteRole(e.currentTarget.value)}>
              <option value="admin">{t("admin.roleAdmin")}</option>
              <option value="moderator">{t("admin.roleModerator")}</option>
              <option value="user">{t("admin.roleUser")}</option>
            </select>
          </div>
        </Show>
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

  const [confirmAction, setConfirmAction] = createSignal<{
    type: "suspend" | "silence";
    userId: string;
    username: string;
  } | null>(null);
  const [confirmInput, setConfirmInput] = createSignal("");
  const [actionLoading, setActionLoading] = createSignal(false);

  const openConfirm = (type: "suspend" | "silence", userId: string, username: string) => {
    setConfirmInput("");
    setConfirmAction({ type, userId, username });
  };

  const closeConfirm = () => {
    setConfirmAction(null);
    setConfirmInput("");
    setActionLoading(false);
  };

  const executeConfirm = async () => {
    const action = confirmAction();
    if (!action) return;
    setActionLoading(true);
    try {
      if (action.type === "suspend") {
        await suspendUser(action.userId);
      } else {
        await silenceUser(action.userId);
      }
      await reload();
      closeConfirm();
    } catch {
      setActionLoading(false);
    }
  };

  const confirmMatches = () => {
    const action = confirmAction();
    if (!action) return false;
    return confirmInput() === `@${action.username}`;
  };

  const handleUnsuspend = async (userId: string) => {
    try { await unsuspendUser(userId); await reload(); } catch {}
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
                      <button class="btn btn-small btn-danger" onClick={() => openConfirm("suspend", u.id, u.username)}>
                        {t("admin.suspend")}
                      </button>
                    </Show>
                    <Show when={u.suspended}>
                      <button class="btn btn-small" onClick={() => handleUnsuspend(u.id)}>
                        {t("admin.unsuspend")}
                      </button>
                    </Show>
                    <Show when={!u.silenced}>
                      <button class="btn btn-small" onClick={() => openConfirm("silence", u.id, u.username)}>
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

      {/* Confirmation modal for suspend/silence */}
      <Show when={confirmAction()}>
        {(action) => (
          <div class="modal-overlay" onClick={closeConfirm}>
            <div class="modal-content" style="max-width: 420px" onClick={(e) => e.stopPropagation()}>
              <div class="modal-header">
                <h3>
                  {action().type === "suspend"
                    ? t("admin.confirmSuspendTitle")
                    : t("admin.confirmSilenceTitle")}
                </h3>
                <button class="modal-close" onClick={closeConfirm}>✕</button>
              </div>
              <div style="padding: 16px">
                <p class="confirm-input-hint">
                  {t("admin.typeToConfirm").replace("{username}", action().username)}
                </p>
                <input
                  class="confirm-input"
                  type="text"
                  value={confirmInput()}
                  onInput={(e) => setConfirmInput(e.currentTarget.value)}
                  placeholder={`@${action().username}`}
                  autofocus
                />
                <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px">
                  <button class="btn btn-small" onClick={closeConfirm}>
                    {t("common.cancel")}
                  </button>
                  <button
                    class="btn btn-small btn-danger"
                    disabled={!confirmMatches() || actionLoading()}
                    onClick={executeConfirm}
                  >
                    {action().type === "suspend"
                      ? t("admin.suspend")
                      : t("admin.silence")}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </Show>
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

function EmojiTab() {
  const { t } = useI18n();
  const [emojis, setEmojis] = createSignal<AdminEmoji[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [showForm, setShowForm] = createSignal(false);
  const [importing, setImporting] = createSignal(false);
  const [importMsg, setImportMsg] = createSignal("");

  // Remote emoji state
  const [remoteEmojis, setRemoteEmojis] = createSignal<RemoteEmoji[]>([]);
  const [remoteDomains, setRemoteDomains] = createSignal<string[]>([]);
  const [remoteLoading, setRemoteLoading] = createSignal(false);
  const [remoteDomain, setRemoteDomain] = createSignal("");
  const [remoteSearch, setRemoteSearch] = createSignal("");
  const [remoteMsg, setRemoteMsg] = createSignal("");
  const [importingId, setImportingId] = createSignal("");
  const [shortcode, setShortcode] = createSignal("");
  const [category, setCategory] = createSignal("");
  const [aliases, setAliases] = createSignal("");
  const [license, setLicense] = createSignal("");
  const [author, setAuthor] = createSignal("");
  const [description, setDescription] = createSignal("");
  const [copyPermission, setCopyPermission] = createSignal("");
  const [isSensitive, setIsSensitive] = createSignal(false);
  const [localOnly, setLocalOnly] = createSignal(false);
  const [adding, setAdding] = createSignal(false);
  let fileInput!: HTMLInputElement;
  let importInput!: HTMLInputElement;

  const load = async () => {
    try { setEmojis(await getAdminEmojis()); } catch {}
    setLoading(false);
  };

  onMount(load);

  const handleAdd = async () => {
    const file = fileInput.files?.[0];
    if (!file || !shortcode().trim()) return;
    setAdding(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("shortcode", shortcode().trim());
    if (category()) fd.append("category", category());
    if (aliases()) fd.append("aliases", JSON.stringify(aliases().split(",").map(a => a.trim()).filter(Boolean)));
    if (license()) fd.append("license", license());
    if (author()) fd.append("author", author());
    if (description()) fd.append("description", description());
    if (copyPermission()) fd.append("copy_permission", copyPermission());
    fd.append("is_sensitive", String(isSensitive()));
    fd.append("local_only", String(localOnly()));
    try {
      await addEmoji(fd);
      setShortcode(""); setCategory(""); setAliases(""); setLicense("");
      setAuthor(""); setDescription(""); setCopyPermission("");
      setIsSensitive(false); setLocalOnly(false);
      fileInput.value = "";
      setShowForm(false);
      await load();
    } catch {}
    setAdding(false);
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("admin.confirmDeleteEmoji"))) return;
    try { await deleteEmoji(id); await load(); } catch {}
  };

  const loadRemote = async () => {
    setRemoteLoading(true);
    try {
      const [ems, doms] = await Promise.all([
        getRemoteEmojis(remoteDomain() || undefined, remoteSearch() || undefined),
        getRemoteEmojiDomains(),
      ]);
      setRemoteEmojis(ems);
      setRemoteDomains(doms);
    } catch {}
    setRemoteLoading(false);
  };

  const handleImportRemote = async (id: string) => {
    setImportingId(id);
    setRemoteMsg("");
    try {
      await importRemoteEmoji(id);
      setRemoteMsg(t("admin.importSuccess"));
      await load();
      await loadRemote();
    } catch (e: any) {
      setRemoteMsg(e.message || t("admin.importFailed"));
    }
    setImportingId("");
  };

  const handleImport = async (e: Event) => {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    setImporting(true);
    setImportMsg("");
    try {
      const res = await importEmojis(file);
      setImportMsg(t("admin.importResult").replace("{imported}", String(res.imported)).replace("{skipped}", String(res.skipped)));
      await load();
    } catch { setImportMsg("Import failed"); }
    setImporting(false);
    (e.currentTarget as HTMLInputElement).value = "";
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabEmoji")}</h3>
      <div class="admin-emoji-actions">
        <button class="btn btn-small" onClick={() => setShowForm(!showForm())}>{t("admin.emojiAdd")}</button>
        <button class="btn btn-small" onClick={() => importInput.click()} disabled={importing()}>
          {importing() ? t("common.loading") : t("admin.emojiImport")}
        </button>
        <a class="btn btn-small" href={getEmojiExportUrl()} download="">{t("admin.emojiExport")}</a>
        <input ref={importInput} type="file" accept=".zip" style="display:none" onChange={handleImport} />
      </div>
      <Show when={importMsg()}><p class="settings-success">{importMsg()}</p></Show>

      <Show when={showForm()}>
        <div class="admin-emoji-form">
          <div class="settings-form-group">
            <label>{t("admin.emojiFile")}</label>
            <input ref={fileInput} type="file" accept="image/*" />
          </div>
          <div class="settings-form-group">
            <label>{t("admin.emojiShortcode")}</label>
            <input type="text" value={shortcode()} onInput={(e) => setShortcode(e.currentTarget.value)} placeholder="neko_smile" />
          </div>
          <div class="admin-emoji-form-row">
            <div class="settings-form-group">
              <label>{t("admin.emojiCategory")}</label>
              <input type="text" value={category()} onInput={(e) => setCategory(e.currentTarget.value)} />
            </div>
            <div class="settings-form-group">
              <label>{t("admin.emojiAliases")}</label>
              <input type="text" value={aliases()} onInput={(e) => setAliases(e.currentTarget.value)} />
            </div>
          </div>
          <div class="admin-emoji-form-row">
            <div class="settings-form-group">
              <label>{t("admin.emojiLicense")}</label>
              <input type="text" value={license()} onInput={(e) => setLicense(e.currentTarget.value)} />
            </div>
            <div class="settings-form-group">
              <label>{t("admin.emojiAuthor")}</label>
              <input type="text" value={author()} onInput={(e) => setAuthor(e.currentTarget.value)} />
            </div>
          </div>
          <div class="settings-form-group">
            <label>{t("admin.emojiDescription")}</label>
            <input type="text" value={description()} onInput={(e) => setDescription(e.currentTarget.value)} />
          </div>
          <div class="settings-form-group">
            <label>{t("admin.emojiCopyPermission")}</label>
            <select value={copyPermission()} onChange={(e) => setCopyPermission(e.currentTarget.value)}>
              <option value="">--</option>
              <option value="allow">allow</option>
              <option value="deny">deny</option>
              <option value="conditional">conditional</option>
            </select>
          </div>
          <div class="admin-emoji-form-row">
            <label class="toggle-label">
              <input type="checkbox" checked={isSensitive()} onChange={(e) => setIsSensitive(e.currentTarget.checked)} />
              {t("admin.emojiSensitive")}
            </label>
            <label class="toggle-label">
              <input type="checkbox" checked={localOnly()} onChange={(e) => setLocalOnly(e.currentTarget.checked)} />
              {t("admin.emojiLocalOnly")}
            </label>
          </div>
          <button class="btn btn-small" onClick={handleAdd} disabled={adding() || !shortcode().trim()}>
            {adding() ? t("common.loading") : t("admin.emojiAdd")}
          </button>
        </div>
      </Show>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={emojis().length > 0} fallback={<p class="empty">{t("admin.noEmoji")}</p>}>
          <div class="admin-emoji-list">
            <For each={emojis()}>
              {(e) => (
                <div class="admin-emoji-item">
                  <img src={e.url} alt={e.shortcode} class="admin-emoji-img" loading="lazy" />
                  <div class="admin-emoji-info">
                    <strong>:{e.shortcode}:</strong>
                    <Show when={e.category}><span class="admin-emoji-cat">{e.category}</span></Show>
                    <Show when={e.license}><span class="admin-emoji-meta">{e.license}</span></Show>
                    <Show when={e.author}><span class="admin-emoji-meta">{e.author}</span></Show>
                  </div>
                  <button class="btn btn-small btn-danger" onClick={() => handleDelete(e.id)}>
                    {t("admin.remove")}
                  </button>
                </div>
              )}
            </For>
          </div>
        </Show>
      </Show>

      <h3>{t("admin.remoteEmoji")}</h3>
      <div class="admin-remote-emoji-actions">
        <select
          value={remoteDomain()}
          onChange={(e) => { setRemoteDomain(e.currentTarget.value); }}
        >
          <option value="">{t("admin.allDomains")}</option>
          <For each={remoteDomains()}>
            {(d) => <option value={d}>{d}</option>}
          </For>
        </select>
        <input
          type="text"
          value={remoteSearch()}
          onInput={(e) => setRemoteSearch(e.currentTarget.value)}
          placeholder={t("admin.searchEmoji")}
        />
        <button class="btn btn-small" onClick={loadRemote} disabled={remoteLoading()}>
          {remoteLoading() ? t("common.loading") : t("admin.search")}
        </button>
      </div>
      <Show when={remoteMsg()}><p class="settings-success">{remoteMsg()}</p></Show>

      <Show when={remoteEmojis().length > 0}>
        <div class="admin-emoji-list">
          <For each={remoteEmojis()}>
            {(e) => (
              <div class="admin-emoji-item">
                <img src={e.url} alt={e.shortcode} class="admin-emoji-img" loading="lazy" />
                <div class="admin-emoji-info">
                  <strong>:{e.shortcode}:</strong>
                  <span class="admin-emoji-meta">@{e.domain}</span>
                  <Show when={e.copy_permission === "deny"}>
                    <span class="admin-emoji-meta" style="color: var(--accent)">{t("admin.copyDenied")}</span>
                  </Show>
                </div>
                <button
                  class="btn btn-small"
                  onClick={() => handleImportRemote(e.id)}
                  disabled={importingId() === e.id || e.copy_permission === "deny"}
                >
                  {importingId() === e.id ? t("common.loading") : t("admin.importEmoji")}
                </button>
              </div>
            )}
          </For>
        </div>
      </Show>
      <Show when={!remoteLoading() && remoteEmojis().length === 0 && remoteDomains().length > 0}>
        <p class="empty">{t("admin.noRemoteEmoji")}</p>
      </Show>
    </div>
  );
}

function ServerFilesTab() {
  const { t } = useI18n();
  const [files, setFiles] = createSignal<ServerFile[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [uploading, setUploading] = createSignal(false);
  const [copied, setCopied] = createSignal<string | null>(null);
  let fileInput!: HTMLInputElement;

  const load = async () => {
    try { setFiles(await getServerFiles()); } catch {}
    setLoading(false);
  };

  onMount(load);

  const handleUpload = async (e: Event) => {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await uploadServerFile(file);
      await load();
    } catch {}
    setUploading(false);
    (e.currentTarget as HTMLInputElement).value = "";
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("admin.confirmDeleteFile"))) return;
    try { await deleteServerFile(id); await load(); } catch {}
  };

  const copyUrl = (url: string) => {
    navigator.clipboard.writeText(url);
    setCopied(url);
    setTimeout(() => setCopied(null), 2000);
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabFiles")}</h3>
      <div class="admin-emoji-actions">
        <button class="btn btn-small" onClick={() => fileInput.click()} disabled={uploading()}>
          {uploading() ? t("common.loading") : t("admin.uploadFile")}
        </button>
        <input ref={fileInput} type="file" style="display:none" onChange={handleUpload} />
      </div>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={files().length > 0} fallback={<p class="empty">{t("admin.noFiles")}</p>}>
          <div class="admin-file-list">
            <For each={files()}>
              {(f) => (
                <div class="admin-file-item">
                  <Show when={f.mime_type.startsWith("image/")}>
                    <img src={f.url} alt={f.filename} class="admin-file-thumb" loading="lazy" />
                  </Show>
                  <div class="admin-file-info">
                    <strong>{f.filename}</strong>
                    <span class="admin-file-meta">{formatSize(f.size_bytes)}</span>
                  </div>
                  <div class="admin-file-actions">
                    <button class="btn btn-small" onClick={() => copyUrl(f.url)}>
                      {copied() === f.url ? t("admin.copied") : t("admin.copyUrl")}
                    </button>
                    <button class="btn btn-small btn-danger" onClick={() => handleDelete(f.id)}>
                      {t("admin.remove")}
                    </button>
                  </div>
                </div>
              )}
            </For>
          </div>
        </Show>
      </Show>
    </div>
  );
}

function InvitesTab() {
  const { t } = useI18n();
  const [invites, setInvites] = createSignal<InviteCode[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [creating, setCreating] = createSignal(false);
  const [copied, setCopied] = createSignal("");

  const load = async () => {
    try { setInvites(await getInviteCodes()); } catch {}
    setLoading(false);
  };

  onMount(load);

  const handleCreate = async () => {
    setCreating(true);
    try {
      await createInviteCode();
      await load();
    } catch {}
    setCreating(false);
  };

  const handleRevoke = async (code: string) => {
    if (!confirm(t("admin.confirmRevokeInvite"))) return;
    try { await revokeInviteCode(code); await load(); } catch {}
  };

  const copyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(code);
    setTimeout(() => setCopied(""), 2000);
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabInvites")}</h3>
      <button class="btn btn-small" onClick={handleCreate} disabled={creating()}>
        {creating() ? t("common.loading") : t("admin.createInvite")}
      </button>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={invites().length > 0} fallback={<p class="empty">{t("admin.noInvites")}</p>}>
          <div class="admin-invite-list">
            <For each={invites()}>
              {(inv) => (
                <div class={`admin-invite-item${inv.used_by ? " used" : ""}`}>
                  <div class="admin-invite-info">
                    <code class="admin-invite-code">{inv.code}</code>
                    <Show when={inv.used_by} fallback={
                      <span class="admin-invite-unused">{t("admin.inviteUnused")}</span>
                    }>
                      <span class="admin-invite-used">
                        {t("admin.inviteUsedBy")} @{inv.used_by}
                      </span>
                    </Show>
                    <span class="admin-invite-time">
                      {new Date(inv.created_at).toLocaleString()}
                    </span>
                  </div>
                  <Show when={!inv.used_by}>
                    <div class="admin-invite-actions">
                      <button class="btn btn-small" onClick={() => copyCode(inv.code)}>
                        {copied() === inv.code ? t("admin.copied") : t("admin.copyUrl")}
                      </button>
                      <button class="btn btn-small btn-danger" onClick={() => handleRevoke(inv.code)}>
                        {t("admin.remove")}
                      </button>
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
