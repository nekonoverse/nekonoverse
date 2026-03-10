import {
  createSignal,
  createMemo,
  createEffect,
  onCleanup,
  Show,
  For,
  Switch,
  Match,
} from "solid-js";
import { useParams, A } from "@solidjs/router";
import { useI18n } from "../i18n";
import { currentUser } from "../stores/auth";
import { registrationMode } from "../stores/instance";
import Breadcrumb from "../components/Breadcrumb";
import {
  getAdminStats,
  getServerSettings,
  updateServerSettings,
  getAdminUsers,
  changeUserRole,
  suspendUser,
  unsuspendUser,
  silenceUser,
  unsilenceUser,
  getDomainBlocks,
  createDomainBlock,
  removeDomainBlock,
  getReports,
  resolveReport,
  rejectReport,
  getModerationLog,
  uploadServerIcon,
  markNoteSensitive,
  getAdminEmojis,
  addEmoji,
  deleteEmoji,
  importEmojis,
  getEmojiExportUrl,
  getRemoteEmojis,
  getRemoteEmojiDomains,
  importRemoteEmoji,
  getServerFiles,
  uploadServerFile,
  deleteServerFile,
  getInviteCodes,
  createInviteCode,
  revokeInviteCode,
  getFederatedServers,
  getFederatedServerDetail,
  getQueueStats,
  getQueueJobs,
  retryQueueJob,
  retryAllDeadJobs,
  purgeDeliveredJobs,
  getSystemStats,
  getPendingRegistrations,
  approveRegistration,
  rejectRegistration,
  type AdminStats,
  type ServerSettings,
  type AdminUser,
  type DomainBlock,
  type Report,
  type ModerationLogEntry,
  type AdminEmoji,
  type RemoteEmoji,
  type ServerFile,
  type InviteCode,
  type FederatedServer,
  type FederatedServerDetail,
  type FederatedServerList,
  type QueueStats,
  type QueueJob,
  type QueueJobList,
  type SystemStats,
  type PendingRegistration,
} from "../api/admin";

interface AdminSection {
  key: string;
  labelKey: string;
  descKey: string;
}

interface AdminCategory {
  labelKey: string;
  adminOnly: boolean;
  sections: AdminSection[];
}

const categories: AdminCategory[] = [
  {
    labelKey: "admin.categoryModeration",
    adminOnly: false,
    sections: [
      { key: "users", labelKey: "admin.tabUsers", descKey: "admin.descUsers" },
      {
        key: "registrations",
        labelKey: "admin.tabRegistrations",
        descKey: "admin.descRegistrations",
      },
      {
        key: "domains",
        labelKey: "admin.tabDomains",
        descKey: "admin.descDomains",
      },
      {
        key: "reports",
        labelKey: "admin.tabReports",
        descKey: "admin.descReports",
      },
      { key: "log", labelKey: "admin.tabLog", descKey: "admin.descLog" },
    ],
  },
  {
    labelKey: "admin.categoryFederation",
    adminOnly: false,
    sections: [
      {
        key: "federation",
        labelKey: "admin.tabFederation",
        descKey: "admin.descFederation",
      },
    ],
  },
  {
    labelKey: "admin.categoryServer",
    adminOnly: true,
    sections: [
      {
        key: "settings",
        labelKey: "admin.tabSettings",
        descKey: "admin.descSettings",
      },
      { key: "emoji", labelKey: "admin.tabEmoji", descKey: "admin.descEmoji" },
      { key: "files", labelKey: "admin.tabFiles", descKey: "admin.descFiles" },
      {
        key: "invites",
        labelKey: "admin.tabInvites",
        descKey: "admin.descInvites",
      },
      {
        key: "queue",
        labelKey: "admin.tabQueue",
        descKey: "admin.descQueue",
      },
      {
        key: "system",
        labelKey: "admin.tabSystem",
        descKey: "admin.descSystem",
      },
    ],
  },
];

function findSectionLabel(t: (key: any) => string, sectionKey: string): string {
  for (const cat of categories) {
    for (const s of cat.sections) {
      if (s.key === sectionKey) return t(s.labelKey as any);
    }
  }
  return "";
}

export default function Admin() {
  const { t } = useI18n();
  const params = useParams<{ section?: string }>();

  const section = () => params.section || "";

  const isStaff = () => {
    const u = currentUser();
    return u && (u.role === "admin" || u.role === "moderator");
  };

  const isAdmin = () => currentUser()?.role === "admin";

  return (
    <div class="page-container admin-page">
      <Show
        when={isStaff()}
        fallback={<p class="error">{t("admin.noAccess")}</p>}
      >
        <Show
          when={section()}
          fallback={
            <>
              <h1>{t("admin.title")}</h1>
              <OverviewTab />
              <div class="settings-menu">
                <For each={categories}>
                  {(cat) => (
                    <Show when={!cat.adminOnly || isAdmin()}>
                      <div class="settings-menu-category">
                        <h3 class="settings-menu-category-title">
                          {t(cat.labelKey as any)}
                        </h3>
                        <div class="settings-menu-grid">
                          <For each={cat.sections.filter(
                            (s) => s.key !== "registrations" || registrationMode() === "approval"
                          )}>
                            {(s) => (
                              <A
                                href={`/admin/${s.key}`}
                                class="settings-menu-card"
                              >
                                <span class="settings-menu-card-title">
                                  {t(s.labelKey as any)}
                                </span>
                                <span class="settings-menu-card-desc">
                                  {t(s.descKey as any)}
                                </span>
                              </A>
                            )}
                          </For>
                        </div>
                      </div>
                    </Show>
                  )}
                </For>
              </div>
            </>
          }
        >
          <Breadcrumb
            items={[
              { label: t("admin.title"), href: "/admin" },
              { label: findSectionLabel(t, section()) },
            ]}
          />
          <Switch>
            <Match when={section() === "settings"}>
              <ServerSettingsTab />
            </Match>
            <Match when={section() === "users"}>
              <UsersTab />
            </Match>
            <Match when={section() === "registrations"}>
              <RegistrationsTab />
            </Match>
            <Match when={section() === "domains"}>
              <DomainsTab />
            </Match>
            <Match when={section() === "federation"}>
              <FederationTab />
            </Match>
            <Match when={section() === "reports"}>
              <ReportsTab />
            </Match>
            <Match when={section() === "log"}>
              <LogTab />
            </Match>
            <Match when={section() === "emoji"}>
              <EmojiTab />
            </Match>
            <Match when={section() === "files"}>
              <ServerFilesTab />
            </Match>
            <Match when={section() === "invites"}>
              <InvitesTab />
            </Match>
            <Match when={section() === "queue"}>
              <QueueTab />
            </Match>
            <Match when={section() === "system"}>
              <SystemTab />
            </Match>
          </Switch>
        </Show>
      </Show>
    </div>
  );
}

function OverviewTab() {
  const { t } = useI18n();
  const [stats, setStats] = createSignal<AdminStats | null>(null);

  // Use createEffect for reliable initialization inside Switch/Match
  let overviewInit = false;
  createEffect(() => {
    if (!overviewInit) {
      overviewInit = true;
      (async () => {
        try {
          setStats(await getAdminStats());
        } catch (e) {
          console.error("Failed to load admin stats:", e);
        }
      })();
    }
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
  const [themeColor, setThemeColor] = createSignal("");
  const [iconUrl, setIconUrl] = createSignal("");
  const [uploadingIcon, setUploadingIcon] = createSignal(false);
  let iconInput!: HTMLInputElement;

  // Use createEffect for reliable initialization inside Switch/Match
  let settingsInit = false;
  createEffect(() => {
    if (!settingsInit) {
      settingsInit = true;
      (async () => {
        try {
          const s = await getServerSettings();
          setSettings(s);
          setName(s.server_name || "");
          setDesc(s.server_description || "");
          setTos(s.tos_url || "");
          setRegMode(s.registration_mode || "open");
          setInviteRole(s.invite_create_role || "admin");
          setThemeColor(s.server_theme_color || "");
          if (s.server_icon_url) setIconUrl(s.server_icon_url);
        } catch (e) {
          console.error("Failed to load server settings:", e);
        }
      })();
    }
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
        server_theme_color: themeColor() || null,
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
        <Show when={saved()}>
          <p class="settings-success">{t("settings.saved")}</p>
        </Show>
        <div class="settings-form-group">
          <label>{t("admin.serverName")}</label>
          <input
            type="text"
            value={name()}
            onInput={(e) => setName(e.currentTarget.value)}
          />
        </div>
        <div class="settings-form-group">
          <label>{t("admin.serverDesc")}</label>
          <textarea
            rows={3}
            value={desc()}
            onInput={(e) => setDesc(e.currentTarget.value)}
          />
        </div>
        <div class="settings-form-group">
          <label>{t("admin.tosUrl")}</label>
          <input
            type="text"
            value={tos()}
            onInput={(e) => setTos(e.currentTarget.value)}
          />
        </div>
        <div class="settings-form-group">
          <label>{t("admin.themeColor")}</label>
          <div style={{ display: "flex", gap: "8px", "align-items": "center" }}>
            <input
              type="color"
              value={themeColor() || "#f5e6f0"}
              onInput={(e) => setThemeColor(e.currentTarget.value)}
              style={{ width: "48px", height: "36px", padding: "2px", cursor: "pointer" }}
            />
            <input
              type="text"
              value={themeColor()}
              onInput={(e) => setThemeColor(e.currentTarget.value)}
              placeholder="#f5e6f0"
              maxlength={7}
              style={{ "max-width": "120px" }}
            />
          </div>
        </div>
        <div class="settings-form-group">
          <label>{t("admin.registrationMode")}</label>
          <select
            value={regMode()}
            onChange={(e) => setRegMode(e.currentTarget.value)}
          >
            <option value="open">{t("admin.regModeOpen")}</option>
            <option value="invite">{t("admin.regModeInvite")}</option>
            <option value="approval">{t("admin.regModeApproval")}</option>
            <option value="closed">{t("admin.regModeClosed")}</option>
          </select>
        </div>
        <Show when={regMode() === "invite"}>
          <div class="settings-form-group">
            <label>{t("admin.inviteCreateRole")}</label>
            <select
              value={inviteRole()}
              onChange={(e) => setInviteRole(e.currentTarget.value)}
            >
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
          <img
            src={iconUrl()}
            alt="Server icon"
            class="admin-server-icon-preview"
          />
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
      <Show when={marked()}>
        <p class="settings-success">{t("admin.markedSensitive")}</p>
      </Show>
      <div class="admin-domain-form">
        <input
          type="text"
          placeholder={t("admin.noteIdPlaceholder")}
          value={noteId()}
          onInput={(e) => setNoteId(e.currentTarget.value)}
        />
        <button
          class="btn btn-small"
          onClick={handleMark}
          disabled={marking() || !noteId().trim()}
        >
          {t("admin.markSensitive")}
        </button>
      </div>
    </div>
  );
}

function RegistrationsTab() {
  const { t } = useI18n();
  const [registrations, setRegistrations] = createSignal<PendingRegistration[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal("");

  const reload = async () => {
    setLoading(true);
    try {
      setRegistrations(await getPendingRegistrations());
      setError("");
    } catch {
      setError(t("common.loadError"));
    } finally {
      setLoading(false);
    }
  };

  createEffect(() => {
    reload();
  });

  const handleApprove = async (userId: string) => {
    try {
      await approveRegistration(userId);
      await reload();
    } catch {}
  };

  const handleReject = async (userId: string) => {
    if (!confirm(t("admin.confirmRejectRegistration"))) return;
    try {
      await rejectRegistration(userId);
      await reload();
    } catch {}
  };

  return (
    <>
      <div class="settings-section">
        <h3>{t("admin.tabRegistrations")}</h3>
        <Show when={error()}>
          <div class="error">{error()}</div>
        </Show>
        <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
          <Show
            when={registrations().length > 0}
            fallback={<p class="admin-empty">{t("admin.noRegistrations")}</p>}
          >
            <div class="admin-table-container">
              <table class="admin-table">
                <thead>
                  <tr>
                    <th>{t("auth.username")}</th>
                    <th>{t("auth.email")}</th>
                    <th>{t("auth.reason")}</th>
                    <th>{t("admin.createdAt")}</th>
                    <th>{t("admin.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  <For each={registrations()}>
                    {(reg) => (
                      <tr>
                        <td>{reg.username}</td>
                        <td>{reg.email}</td>
                        <td class="admin-registration-reason">
                          {reg.reason || "-"}
                        </td>
                        <td>{new Date(reg.created_at).toLocaleString()}</td>
                        <td class="admin-actions">
                          <button
                            class="btn btn-small btn-primary"
                            onClick={() => handleApprove(reg.id)}
                          >
                            {t("admin.approve")}
                          </button>
                          <button
                            class="btn btn-small btn-danger"
                            onClick={() => handleReject(reg.id)}
                          >
                            {t("admin.reject")}
                          </button>
                        </td>
                      </tr>
                    )}
                  </For>
                </tbody>
              </table>
            </div>
          </Show>
        </Show>
      </div>
    </>
  );
}

function UsersTab() {
  const { t } = useI18n();
  const [users, setUsers] = createSignal<AdminUser[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal("");
  const isAdmin = () => currentUser()?.role === "admin";
  const isSelf = (userId: string) => currentUser()?.id === userId;

  const loadUsers = async () => {
    setLoading(true);
    setError("");
    try {
      setUsers(await getAdminUsers());
    } catch (e) {
      console.error("Failed to load admin users:", e);
      setError(e instanceof Error ? e.message : "Failed to load users");
    }
    setLoading(false);
  };

  // Use createEffect for reliable initialization inside Switch/Match
  let usersInit = false;
  createEffect(() => {
    if (!usersInit) {
      usersInit = true;
      loadUsers();
    }
  });

  const reload = async () => {
    setError("");
    try {
      setUsers(await getAdminUsers());
    } catch (e) {
      console.error("Failed to reload admin users:", e);
      setError(e instanceof Error ? e.message : "Failed to load users");
    }
  };

  const handleRoleChange = async (userId: string, role: string) => {
    try {
      await changeUserRole(userId, role);
      await reload();
    } catch {}
  };

  const [confirmAction, setConfirmAction] = createSignal<{
    type: "suspend" | "silence";
    userId: string;
    username: string;
  } | null>(null);
  const [confirmInput, setConfirmInput] = createSignal("");
  const [actionLoading, setActionLoading] = createSignal(false);

  const openConfirm = (
    type: "suspend" | "silence",
    userId: string,
    username: string,
  ) => {
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
    try {
      await unsuspendUser(userId);
      await reload();
    } catch {}
  };

  const handleUnsilence = async (userId: string) => {
    try {
      await unsilenceUser(userId);
      await reload();
    } catch {}
  };

  return (
    <>
      <div class="settings-section">
        <h3>{t("admin.tabUsers")}</h3>
        <Show when={error()}>
          <p class="error">{error()}</p>
        </Show>
        <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
          <div class="admin-user-list">
            <For each={users()}>
              {(u) => (
                <div
                  class={`admin-user-item${u.suspended ? " suspended" : ""}${u.silenced ? " silenced" : ""}`}
                >
                  <div class="admin-user-info">
                    <strong>{u.display_name || u.username}</strong>
                    <span class="admin-user-handle">@{u.username}</span>
                    <span class={`admin-role-badge role-${u.role}`}>
                      {u.role}
                    </span>
                    <Show when={u.suspended}>
                      <span class="admin-status-badge suspended">
                        {t("admin.suspended")}
                      </span>
                    </Show>
                    <Show when={u.silenced}>
                      <span class="admin-status-badge silenced">
                        {t("admin.silenced")}
                      </span>
                    </Show>
                  </div>
                  <Show when={!isSelf(u.id)}>
                    <div class="admin-user-actions">
                      <Show when={isAdmin()}>
                        <select
                          value={u.role}
                          onChange={(e) =>
                            handleRoleChange(u.id, e.currentTarget.value)
                          }
                        >
                          <option value="user">user</option>
                          <option value="moderator">moderator</option>
                          <option value="admin">admin</option>
                        </select>
                      </Show>
                      <Show when={!u.suspended}>
                        <button
                          class="btn btn-small btn-danger"
                          onClick={() => openConfirm("suspend", u.id, u.username)}
                        >
                          {t("admin.suspend")}
                        </button>
                      </Show>
                      <Show when={u.suspended}>
                        <button
                          class="btn btn-small"
                          onClick={() => handleUnsuspend(u.id)}
                        >
                          {t("admin.unsuspend")}
                        </button>
                      </Show>
                      <Show when={!u.silenced}>
                        <button
                          class="btn btn-small"
                          onClick={() => openConfirm("silence", u.id, u.username)}
                        >
                          {t("admin.silence")}
                        </button>
                      </Show>
                      <Show when={u.silenced}>
                        <button
                          class="btn btn-small"
                          onClick={() => handleUnsilence(u.id)}
                        >
                          {t("admin.unsilence")}
                        </button>
                      </Show>
                    </div>
                  </Show>
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
            <div
              class="modal-content"
              style="max-width: 420px"
              onClick={(e) => e.stopPropagation()}
            >
              <div class="modal-header">
                <h3>
                  {action().type === "suspend"
                    ? t("admin.confirmSuspendTitle")
                    : t("admin.confirmSilenceTitle")}
                </h3>
                <button class="modal-close" onClick={closeConfirm}>
                  ✕
                </button>
              </div>
              <div style="padding: 16px">
                <p class="confirm-input-hint">
                  {t("admin.typeToConfirm").replace(
                    "{username}",
                    action().username,
                  )}
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

  // Use createEffect for reliable initialization inside Switch/Match
  let domainsInit = false;
  createEffect(() => {
    if (!domainsInit) {
      domainsInit = true;
      (async () => {
        try {
          setBlocks(await getDomainBlocks());
        } catch (e) {
          console.error("Failed to load domain blocks:", e);
        }
        setLoading(false);
      })();
    }
  });

  const handleAdd = async () => {
    if (!newDomain()) return;
    try {
      const block = await createDomainBlock(
        newDomain(),
        newSeverity(),
        newReason() || undefined,
      );
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
        <select
          value={newSeverity()}
          onChange={(e) => setNewSeverity(e.currentTarget.value)}
        >
          <option value="suspend">{t("admin.suspend")}</option>
          <option value="silence">{t("admin.silence")}</option>
        </select>
        <input
          type="text"
          placeholder={t("admin.reasonPlaceholder")}
          value={newReason()}
          onInput={(e) => setNewReason(e.currentTarget.value)}
        />
        <button class="btn btn-small" onClick={handleAdd}>
          {t("admin.addDomainBlock")}
        </button>
      </div>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={blocks().length > 0}
          fallback={<p class="empty">{t("admin.noDomainBlocks")}</p>}
        >
          <div class="admin-domain-list">
            <For each={blocks()}>
              {(b) => (
                <div class="admin-domain-item">
                  <div>
                    <strong>{b.domain}</strong>
                    <span class={`admin-severity-badge ${b.severity}`}>
                      {b.severity}
                    </span>
                    <Show when={b.reason}>
                      <span class="admin-domain-reason">{b.reason}</span>
                    </Show>
                  </div>
                  <button
                    class="btn btn-small btn-danger"
                    onClick={() => handleRemove(b.domain)}
                  >
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
    try {
      setReports(await getReports(filter()));
    } catch (e) {
      console.error("Failed to load reports:", e);
    }
    setLoading(false);
  };

  // Use createEffect for reliable initialization inside Switch/Match
  let reportsInit = false;
  createEffect(() => {
    if (!reportsInit) {
      reportsInit = true;
      load();
    }
  });

  const handleResolve = async (id: string) => {
    try {
      await resolveReport(id);
      await load();
    } catch {}
  };

  const handleReject = async (id: string) => {
    try {
      await rejectReport(id);
      await load();
    } catch {}
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabReports")}</h3>
      <div class="admin-report-filter">
        <button
          class={`btn btn-small${!filter() ? " btn-active" : ""}`}
          onClick={() => {
            setFilter(undefined);
            load();
          }}
        >
          {t("admin.allReports")}
        </button>
        <button
          class={`btn btn-small${filter() === "open" ? " btn-active" : ""}`}
          onClick={() => {
            setFilter("open");
            load();
          }}
        >
          {t("admin.openReports")}
        </button>
      </div>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={reports().length > 0}
          fallback={<p class="empty">{t("admin.noReports")}</p>}
        >
          <div class="admin-report-list">
            <For each={reports()}>
              {(r) => (
                <div class={`admin-report-item status-${r.status}`}>
                  <div class="admin-report-info">
                    <div>
                      <strong>{r.reporter}</strong> →{" "}
                      <strong>{r.target}</strong>
                    </div>
                    <Show when={r.comment}>
                      <p class="admin-report-comment">{r.comment}</p>
                    </Show>
                    <span class="admin-report-time">
                      {new Date(r.created_at).toLocaleString()}
                    </span>
                    <span class={`admin-status-badge ${r.status}`}>
                      {r.status}
                    </span>
                  </div>
                  <Show when={r.status === "open"}>
                    <div class="admin-report-actions">
                      <button
                        class="btn btn-small"
                        onClick={() => handleResolve(r.id)}
                      >
                        {t("admin.resolve")}
                      </button>
                      <button
                        class="btn btn-small"
                        onClick={() => handleReject(r.id)}
                      >
                        {t("admin.reject")}
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

function LogTab() {
  const { t } = useI18n();
  const [entries, setEntries] = createSignal<ModerationLogEntry[]>([]);
  const [loading, setLoading] = createSignal(true);

  // Use createEffect for reliable initialization inside Switch/Match
  let logInit = false;
  createEffect(() => {
    if (!logInit) {
      logInit = true;
      (async () => {
        try {
          setEntries(await getModerationLog());
        } catch (e) {
          console.error("Failed to load moderation log:", e);
        }
        setLoading(false);
      })();
    }
  });

  return (
    <div class="settings-section">
      <h3>{t("admin.tabLog")}</h3>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={entries().length > 0}
          fallback={<p class="empty">{t("admin.noLogs")}</p>}
        >
          <div class="admin-log-list">
            <For each={entries()}>
              {(e) => (
                <div class="admin-log-item">
                  <span class="admin-log-time">
                    {new Date(e.created_at).toLocaleString()}
                  </span>
                  <strong>{e.moderator}</strong>
                  <span class="admin-log-action">{e.action}</span>
                  <span class="admin-log-target">
                    {e.target_type}:{e.target_id}
                  </span>
                  <Show when={e.reason}>
                    <span class="admin-log-reason">({e.reason})</span>
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
    try {
      setEmojis(await getAdminEmojis());
    } catch (e) {
      console.error("Failed to load emojis:", e);
    }
    setLoading(false);
  };

  // Use createEffect for reliable initialization inside Switch/Match
  let emojiInit = false;
  createEffect(() => {
    if (!emojiInit) {
      emojiInit = true;
      load();
    }
  });

  const handleAdd = async () => {
    const file = fileInput.files?.[0];
    if (!file || !shortcode().trim()) return;
    setAdding(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("shortcode", shortcode().trim());
    if (category()) fd.append("category", category());
    if (aliases())
      fd.append(
        "aliases",
        JSON.stringify(
          aliases()
            .split(",")
            .map((a) => a.trim())
            .filter(Boolean),
        ),
      );
    if (license()) fd.append("license", license());
    if (author()) fd.append("author", author());
    if (description()) fd.append("description", description());
    if (copyPermission()) fd.append("copy_permission", copyPermission());
    fd.append("is_sensitive", String(isSensitive()));
    fd.append("local_only", String(localOnly()));
    try {
      await addEmoji(fd);
      setShortcode("");
      setCategory("");
      setAliases("");
      setLicense("");
      setAuthor("");
      setDescription("");
      setCopyPermission("");
      setIsSensitive(false);
      setLocalOnly(false);
      fileInput.value = "";
      setShowForm(false);
      await load();
    } catch {}
    setAdding(false);
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("admin.confirmDeleteEmoji"))) return;
    try {
      await deleteEmoji(id);
      await load();
    } catch {}
  };

  const loadRemote = async () => {
    setRemoteLoading(true);
    try {
      const [ems, doms] = await Promise.all([
        getRemoteEmojis(
          remoteDomain() || undefined,
          remoteSearch() || undefined,
        ),
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
      setImportMsg(
        t("admin.importResult")
          .replace("{imported}", String(res.imported))
          .replace("{skipped}", String(res.skipped)),
      );
      await load();
    } catch {
      setImportMsg("Import failed");
    }
    setImporting(false);
    (e.currentTarget as HTMLInputElement).value = "";
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabEmoji")}</h3>
      <div class="admin-emoji-actions">
        <button class="btn btn-small" onClick={() => setShowForm(!showForm())}>
          {t("admin.emojiAdd")}
        </button>
        <button
          class="btn btn-small"
          onClick={() => importInput.click()}
          disabled={importing()}
        >
          {importing() ? t("common.loading") : t("admin.emojiImport")}
        </button>
        <a class="btn btn-small" href={getEmojiExportUrl()} download="">
          {t("admin.emojiExport")}
        </a>
        <input
          ref={importInput}
          type="file"
          accept=".zip"
          style="display:none"
          onChange={handleImport}
        />
      </div>
      <Show when={importMsg()}>
        <p class="settings-success">{importMsg()}</p>
      </Show>

      <Show when={showForm()}>
        <div class="admin-emoji-form">
          <div class="settings-form-group">
            <label>{t("admin.emojiFile")}</label>
            <input ref={fileInput} type="file" accept="image/*" />
          </div>
          <div class="settings-form-group">
            <label>{t("admin.emojiShortcode")}</label>
            <input
              type="text"
              value={shortcode()}
              onInput={(e) => setShortcode(e.currentTarget.value)}
              placeholder="neko_smile"
            />
          </div>
          <div class="admin-emoji-form-row">
            <div class="settings-form-group">
              <label>{t("admin.emojiCategory")}</label>
              <input
                type="text"
                value={category()}
                onInput={(e) => setCategory(e.currentTarget.value)}
              />
            </div>
            <div class="settings-form-group">
              <label>{t("admin.emojiAliases")}</label>
              <input
                type="text"
                value={aliases()}
                onInput={(e) => setAliases(e.currentTarget.value)}
              />
            </div>
          </div>
          <div class="admin-emoji-form-row">
            <div class="settings-form-group">
              <label>{t("admin.emojiLicense")}</label>
              <input
                type="text"
                value={license()}
                onInput={(e) => setLicense(e.currentTarget.value)}
              />
            </div>
            <div class="settings-form-group">
              <label>{t("admin.emojiAuthor")}</label>
              <input
                type="text"
                value={author()}
                onInput={(e) => setAuthor(e.currentTarget.value)}
              />
            </div>
          </div>
          <div class="settings-form-group">
            <label>{t("admin.emojiDescription")}</label>
            <input
              type="text"
              value={description()}
              onInput={(e) => setDescription(e.currentTarget.value)}
            />
          </div>
          <div class="settings-form-group">
            <label>{t("admin.emojiCopyPermission")}</label>
            <select
              value={copyPermission()}
              onChange={(e) => setCopyPermission(e.currentTarget.value)}
            >
              <option value="">--</option>
              <option value="allow">allow</option>
              <option value="deny">deny</option>
              <option value="conditional">conditional</option>
            </select>
          </div>
          <div class="admin-emoji-form-row">
            <label class="toggle-label">
              <input
                type="checkbox"
                checked={isSensitive()}
                onChange={(e) => setIsSensitive(e.currentTarget.checked)}
              />
              {t("admin.emojiSensitive")}
            </label>
            <label class="toggle-label">
              <input
                type="checkbox"
                checked={localOnly()}
                onChange={(e) => setLocalOnly(e.currentTarget.checked)}
              />
              {t("admin.emojiLocalOnly")}
            </label>
          </div>
          <button
            class="btn btn-small"
            onClick={handleAdd}
            disabled={adding() || !shortcode().trim()}
          >
            {adding() ? t("common.loading") : t("admin.emojiAdd")}
          </button>
        </div>
      </Show>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={emojis().length > 0}
          fallback={<p class="empty">{t("admin.noEmoji")}</p>}
        >
          <div class="admin-emoji-list">
            <For each={emojis()}>
              {(e) => (
                <div class="admin-emoji-item">
                  <img
                    src={e.url}
                    alt={e.shortcode}
                    class="admin-emoji-img"
                    loading="lazy"
                  />
                  <div class="admin-emoji-info">
                    <strong>:{e.shortcode}:</strong>
                    <Show when={e.category}>
                      <span class="admin-emoji-cat">{e.category}</span>
                    </Show>
                    <Show when={e.license}>
                      <span class="admin-emoji-meta">{e.license}</span>
                    </Show>
                    <Show when={e.author}>
                      <span class="admin-emoji-meta">{e.author}</span>
                    </Show>
                  </div>
                  <button
                    class="btn btn-small btn-danger"
                    onClick={() => handleDelete(e.id)}
                  >
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
          onChange={(e) => {
            setRemoteDomain(e.currentTarget.value);
          }}
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
        <button
          class="btn btn-small"
          onClick={loadRemote}
          disabled={remoteLoading()}
        >
          {remoteLoading() ? t("common.loading") : t("admin.search")}
        </button>
      </div>
      <Show when={remoteMsg()}>
        <p class="settings-success">{remoteMsg()}</p>
      </Show>

      <Show when={remoteEmojis().length > 0}>
        <div class="admin-emoji-list">
          <For each={remoteEmojis()}>
            {(e) => (
              <div class="admin-emoji-item">
                <img
                  src={e.url}
                  alt={e.shortcode}
                  class="admin-emoji-img"
                  loading="lazy"
                />
                <div class="admin-emoji-info">
                  <strong>:{e.shortcode}:</strong>
                  <span class="admin-emoji-meta">@{e.domain}</span>
                  <Show when={e.copy_permission === "deny"}>
                    <span class="admin-emoji-meta" style="color: var(--accent)">
                      {t("admin.copyDenied")}
                    </span>
                  </Show>
                </div>
                <button
                  class="btn btn-small"
                  onClick={() => handleImportRemote(e.id)}
                  disabled={
                    importingId() === e.id || e.copy_permission === "deny"
                  }
                >
                  {importingId() === e.id
                    ? t("common.loading")
                    : t("admin.importEmoji")}
                </button>
              </div>
            )}
          </For>
        </div>
      </Show>
      <Show
        when={
          !remoteLoading() &&
          remoteEmojis().length === 0 &&
          remoteDomains().length > 0
        }
      >
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
    try {
      setFiles(await getServerFiles());
    } catch (e) {
      console.error("Failed to load server files:", e);
    }
    setLoading(false);
  };

  // Use createEffect for reliable initialization inside Switch/Match
  let filesInit = false;
  createEffect(() => {
    if (!filesInit) {
      filesInit = true;
      load();
    }
  });

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
    try {
      await deleteServerFile(id);
      await load();
    } catch {}
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
        <button
          class="btn btn-small"
          onClick={() => fileInput.click()}
          disabled={uploading()}
        >
          {uploading() ? t("common.loading") : t("admin.uploadFile")}
        </button>
        <input
          ref={fileInput}
          type="file"
          style="display:none"
          onChange={handleUpload}
        />
      </div>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={files().length > 0}
          fallback={<p class="empty">{t("admin.noFiles")}</p>}
        >
          <div class="admin-file-list">
            <For each={files()}>
              {(f) => (
                <div class="admin-file-item">
                  <Show when={f.mime_type.startsWith("image/")}>
                    <img
                      src={f.url}
                      alt={f.filename}
                      class="admin-file-thumb"
                      loading="lazy"
                    />
                  </Show>
                  <div class="admin-file-info">
                    <strong>{f.filename}</strong>
                    <span class="admin-file-meta">
                      {formatSize(f.size_bytes)}
                    </span>
                  </div>
                  <div class="admin-file-actions">
                    <button
                      class="btn btn-small"
                      onClick={() => copyUrl(f.url)}
                    >
                      {copied() === f.url
                        ? t("admin.copied")
                        : t("admin.copyUrl")}
                    </button>
                    <button
                      class="btn btn-small btn-danger"
                      onClick={() => handleDelete(f.id)}
                    >
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
  const [maxUses, setMaxUses] = createSignal<string>("1");
  const [expiresInDays, setExpiresInDays] = createSignal<string>("");

  const load = async () => {
    try {
      setInvites(await getInviteCodes());
    } catch (e) {
      console.error("Failed to load invite codes:", e);
    }
    setLoading(false);
  };

  // Use createEffect for reliable initialization inside Switch/Match
  let invitesInit = false;
  createEffect(() => {
    if (!invitesInit) {
      invitesInit = true;
      load();
    }
  });

  const handleCreate = async () => {
    setCreating(true);
    try {
      const mu = maxUses();
      const ed = expiresInDays();
      await createInviteCode({
        max_uses: mu === "" ? null : parseInt(mu, 10),
        expires_in_days: ed ? parseInt(ed, 10) : null,
      });
      await load();
    } catch {}
    setCreating(false);
  };

  const handleRevoke = async (code: string) => {
    if (!confirm(t("admin.confirmRevokeInvite"))) return;
    try {
      await revokeInviteCode(code);
      await load();
    } catch {}
  };

  const copyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(code);
    setTimeout(() => setCopied(""), 2000);
  };

  const isExhausted = (inv: InviteCode) =>
    inv.max_uses !== null && inv.use_count >= inv.max_uses;

  const isExpired = (inv: InviteCode) =>
    inv.expires_at !== null && new Date(inv.expires_at) < new Date();

  const isAvailable = (inv: InviteCode) => !isExhausted(inv) && !isExpired(inv);

  const usageLabel = (inv: InviteCode) => {
    if (inv.max_uses === null) return `${inv.use_count}/${t("admin.inviteUnlimited")}`;
    return `${inv.use_count}/${inv.max_uses}`;
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabInvites")}</h3>
      <div class="admin-invite-create-form">
        <div class="admin-invite-create-fields">
          <div class="field">
            <label>{t("admin.inviteMaxUses")}</label>
            <select
              value={maxUses()}
              onChange={(e) => setMaxUses(e.currentTarget.value)}
            >
              <option value="1">{t("admin.inviteSingleUse")}</option>
              <option value="5">5</option>
              <option value="10">10</option>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
              <option value="">{t("admin.inviteUnlimited")}</option>
            </select>
          </div>
          <div class="field">
            <label>{t("admin.inviteExpiry")}</label>
            <select
              value={expiresInDays()}
              onChange={(e) => setExpiresInDays(e.currentTarget.value)}
            >
              <option value="">{t("admin.inviteNoExpiry")}</option>
              <option value="1">1{t("admin.inviteDays")}</option>
              <option value="7">7{t("admin.inviteDays")}</option>
              <option value="30">30{t("admin.inviteDays")}</option>
              <option value="90">90{t("admin.inviteDays")}</option>
              <option value="365">365{t("admin.inviteDays")}</option>
            </select>
          </div>
        </div>
        <button
          class="btn btn-small"
          onClick={handleCreate}
          disabled={creating()}
        >
          {creating() ? t("common.loading") : t("admin.createInvite")}
        </button>
      </div>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={invites().length > 0}
          fallback={<p class="empty">{t("admin.noInvites")}</p>}
        >
          <div class="admin-invite-list">
            <For each={invites()}>
              {(inv) => (
                <div class={`admin-invite-item${!isAvailable(inv) ? " used" : ""}`}>
                  <div class="admin-invite-info">
                    <code class="admin-invite-code">{inv.code}</code>
                    <span class={isAvailable(inv) ? "admin-invite-unused" : "admin-invite-used"}>
                      {t("admin.inviteUsage")}: {usageLabel(inv)}
                    </span>
                    <Show when={inv.expires_at}>
                      <span class={isExpired(inv) ? "admin-invite-used" : "admin-invite-unused"}>
                        {isExpired(inv)
                          ? t("admin.inviteExpired")
                          : `${t("admin.inviteExpiresAt")} ${new Date(inv.expires_at!).toLocaleDateString()}`}
                      </span>
                    </Show>
                    <span class="admin-invite-time">
                      {new Date(inv.created_at).toLocaleString()}
                    </span>
                  </div>
                  <Show when={isAvailable(inv)}>
                    <div class="admin-invite-actions">
                      <button
                        class="btn btn-small"
                        onClick={() => copyCode(inv.code)}
                      >
                        {copied() === inv.code
                          ? t("admin.copied")
                          : t("admin.copyUrl")}
                      </button>
                      <button
                        class="btn btn-small btn-danger"
                        onClick={() => handleRevoke(inv.code)}
                      >
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

function FederationTab() {
  const { t } = useI18n();
  const [servers, setServers] = createSignal<FederatedServer[]>([]);
  const [total, setTotal] = createSignal(0);
  const [loading, setLoading] = createSignal(true);
  const [search, setSearch] = createSignal("");
  const [statusFilter, setStatusFilter] = createSignal("all");
  const [sort, setSort] = createSignal("user_count");
  const [order, setOrder] = createSignal("desc");
  const [offset, setOffset] = createSignal(0);
  const [expandedDomain, setExpandedDomain] = createSignal<string | null>(null);
  const [detail, setDetail] = createSignal<FederatedServerDetail | null>(null);
  const [detailLoading, setDetailLoading] = createSignal(false);
  const limit = 40;

  const load = async () => {
    setLoading(true);
    try {
      const res = await getFederatedServers({
        limit,
        offset: offset(),
        sort: sort(),
        order: order(),
        search: search() || undefined,
        status: statusFilter(),
      });
      setServers(res.servers);
      setTotal(res.total);
    } catch (e) {
      console.error("Failed to load federated servers:", e);
    }
    setLoading(false);
  };

  // Use createEffect for reliable initialization inside Switch/Match
  let federationInit = false;
  createEffect(() => {
    if (!federationInit) {
      federationInit = true;
      load();
    }
  });

  const handleSearch = () => {
    setOffset(0);
    load();
  };

  const handleSort = (col: string) => {
    if (sort() === col) {
      setOrder(order() === "desc" ? "asc" : "desc");
    } else {
      setSort(col);
      setOrder("desc");
    }
    setOffset(0);
    load();
  };

  const handleStatusFilter = (s: string) => {
    setStatusFilter(s);
    setOffset(0);
    load();
  };

  const toggleDetail = async (domain: string) => {
    if (expandedDomain() === domain) {
      setExpandedDomain(null);
      setDetail(null);
      return;
    }
    setExpandedDomain(domain);
    setDetailLoading(true);
    setDetail(null);
    try {
      setDetail(await getFederatedServerDetail(domain));
    } catch {}
    setDetailLoading(false);
  };

  const totalPages = createMemo(() => Math.max(1, Math.ceil(total() / limit)));
  const currentPage = createMemo(() => Math.floor(offset() / limit) + 1);

  const sortIndicator = (col: string) => {
    if (sort() !== col) return "";
    return order() === "asc" ? " \u2191" : " \u2193";
  };

  const deliveryRate = (s: FederatedServer) => {
    const t =
      s.delivery_stats.success +
      s.delivery_stats.failure +
      s.delivery_stats.dead;
    if (t === 0) return "-";
    return Math.round((s.delivery_stats.success / t) * 100) + "%";
  };

  const formatDate = (d: string | null) => {
    if (!d) return "-";
    return new Date(d).toLocaleDateString();
  };

  const statusLabels = {
    all: () => t("admin.federationStatus_all"),
    active: () => t("admin.federationStatus_active"),
    suspended: () => t("admin.federationStatus_suspended"),
    silenced: () => t("admin.federationStatus_silenced"),
  } as const;

  const statusLabel = (s: string) => {
    const fn = statusLabels[s as keyof typeof statusLabels];
    return fn ? fn() : s;
  };

  const emptyMessages = {
    all: () => t("admin.noFederatedServers"),
    active: () => t("admin.noFederatedServers_active"),
    suspended: () => t("admin.noFederatedServers_suspended"),
    silenced: () => t("admin.noFederatedServers_silenced"),
  } as const;

  const emptyMessage = () => {
    const fn = emptyMessages[statusFilter() as keyof typeof emptyMessages];
    return fn ? fn() : t("admin.noFederatedServers");
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabFederation")}</h3>

      <div class="admin-federation-controls">
        <div class="admin-federation-search">
          <input
            type="text"
            placeholder={t("admin.federationSearchPlaceholder")}
            value={search()}
            onInput={(e) => setSearch(e.currentTarget.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          />
          <button class="btn btn-small" onClick={handleSearch}>
            {t("admin.search")}
          </button>
        </div>
        <div class="admin-federation-filters">
          {(["all", "active", "suspended", "silenced"] as const).map((s) => (
            <button
              class={`btn btn-small${statusFilter() === s ? " btn-active" : ""}`}
              onClick={() => handleStatusFilter(s)}
            >
              {statusLabel(s)}
            </button>
          ))}
        </div>
      </div>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={servers().length > 0}
          fallback={<p class="empty">{emptyMessage()}</p>}
        >
          <div class="admin-federation-table-wrap">
            <table class="admin-federation-table">
              <thead>
                <tr>
                  <th class="sortable" onClick={() => handleSort("domain")}>
                    {t("admin.federationDomain")}
                    {sortIndicator("domain")}
                  </th>
                  <th class="sortable" onClick={() => handleSort("user_count")}>
                    {t("admin.federationUsers")}
                    {sortIndicator("user_count")}
                  </th>
                  <th class="sortable" onClick={() => handleSort("note_count")}>
                    {t("admin.federationNotes")}
                    {sortIndicator("note_count")}
                  </th>
                  <th
                    class="sortable"
                    onClick={() => handleSort("last_activity")}
                  >
                    {t("admin.federationLastActivity")}
                    {sortIndicator("last_activity")}
                  </th>
                  <th>{t("admin.federationStatus")}</th>
                  <th>{t("admin.federationDelivery")}</th>
                </tr>
              </thead>
              <tbody>
                <For each={servers()}>
                  {(s) => (
                    <>
                      <tr
                        class={`admin-federation-row${expandedDomain() === s.domain ? " expanded" : ""}`}
                        onClick={() => toggleDetail(s.domain)}
                      >
                        <td class="admin-federation-domain">{s.domain}</td>
                        <td>{s.user_count}</td>
                        <td>{s.note_count}</td>
                        <td>{formatDate(s.last_activity_at)}</td>
                        <td>
                          <span class={`admin-status-badge ${s.status}`}>
                            {statusLabel(s.status)}
                          </span>
                        </td>
                        <td>{deliveryRate(s)}</td>
                      </tr>
                      <Show when={expandedDomain() === s.domain}>
                        <tr class="admin-federation-detail-row">
                          <td colSpan={6}>
                            <Show
                              when={!detailLoading()}
                              fallback={<p>{t("common.loading")}</p>}
                            >
                              <Show when={detail()}>
                                {(d) => (
                                  <div class="admin-federation-detail">
                                    <div class="admin-federation-detail-stats">
                                      <div class="admin-stat-card">
                                        <span class="admin-stat-num">
                                          {d().delivery_stats.success}
                                        </span>
                                        <span class="admin-stat-label">
                                          {t("admin.federationDeliverySuccess")}
                                        </span>
                                      </div>
                                      <div class="admin-stat-card">
                                        <span class="admin-stat-num">
                                          {d().delivery_stats.failure}
                                        </span>
                                        <span class="admin-stat-label">
                                          {t("admin.federationDeliveryFailure")}
                                        </span>
                                      </div>
                                      <div class="admin-stat-card">
                                        <span class="admin-stat-num">
                                          {d().delivery_stats.pending}
                                        </span>
                                        <span class="admin-stat-label">
                                          {t("admin.federationDeliveryPending")}
                                        </span>
                                      </div>
                                      <div class="admin-stat-card">
                                        <span class="admin-stat-num">
                                          {d().delivery_stats.dead}
                                        </span>
                                        <span class="admin-stat-label">
                                          {t("admin.federationDeliveryDead")}
                                        </span>
                                      </div>
                                    </div>
                                    <Show when={d().first_seen_at}>
                                      <p class="admin-federation-meta">
                                        {t("admin.federationFirstSeen")}:{" "}
                                        {formatDate(d().first_seen_at)}
                                      </p>
                                    </Show>
                                    <Show when={d().block_reason}>
                                      <p class="admin-federation-meta">
                                        {t("admin.federationBlockReason")}:{" "}
                                        {d().block_reason}
                                      </p>
                                    </Show>
                                    <Show when={d().recent_actors.length > 0}>
                                      <h4>
                                        {t("admin.federationRecentActors")}
                                      </h4>
                                      <div class="admin-federation-actors">
                                        <For each={d().recent_actors}>
                                          {(a) => (
                                            <div class="admin-federation-actor">
                                              <strong>
                                                {a.display_name || a.username}
                                              </strong>
                                              <span class="admin-user-handle">
                                                @{a.username}@{d().domain}
                                              </span>
                                            </div>
                                          )}
                                        </For>
                                      </div>
                                    </Show>
                                  </div>
                                )}
                              </Show>
                            </Show>
                          </td>
                        </tr>
                      </Show>
                    </>
                  )}
                </For>
              </tbody>
            </table>
          </div>

          <Show when={totalPages() > 1}>
            <div class="admin-federation-pagination">
              <button
                class="btn btn-small"
                disabled={currentPage() <= 1}
                onClick={() => {
                  setOffset(offset() - limit);
                  load();
                }}
              >
                \u2190
              </button>
              <span>
                {currentPage()} / {totalPages()}
              </span>
              <button
                class="btn btn-small"
                disabled={currentPage() >= totalPages()}
                onClick={() => {
                  setOffset(offset() + limit);
                  load();
                }}
              >
                \u2192
              </button>
            </div>
          </Show>
        </Show>
      </Show>
    </div>
  );
}

function QueueTab() {
  const { t } = useI18n();
  const [stats, setStats] = createSignal<QueueStats | null>(null);
  const [jobs, setJobs] = createSignal<QueueJob[]>([]);
  const [jobTotal, setJobTotal] = createSignal(0);
  const [statusFilter, setStatusFilter] = createSignal("");
  const [domainFilter, setDomainFilter] = createSignal("");
  const [jobOffset, setJobOffset] = createSignal(0);
  const [loading, setLoading] = createSignal(false);
  const [message, setMessage] = createSignal("");
  const jobLimit = 20;

  const loadStats = async () => {
    try {
      setStats(await getQueueStats());
    } catch {}
  };

  const loadJobs = async () => {
    setLoading(true);
    try {
      const res = await getQueueJobs({
        status: statusFilter() || undefined,
        domain: domainFilter() || undefined,
        limit: jobLimit,
        offset: jobOffset(),
      });
      setJobs(res.jobs);
      setJobTotal(res.total);
    } catch {}
    setLoading(false);
  };

  const load = () => {
    loadStats();
    loadJobs();
  };

  // 自動更新: 15秒ごと — use createEffect for reliable initialization inside Switch/Match
  let interval: ReturnType<typeof setInterval>;
  let queueInit = false;
  createEffect(() => {
    if (!queueInit) {
      queueInit = true;
      load();
      interval = setInterval(load, 15000);
    }
  });
  onCleanup(() => clearInterval(interval));

  const handleRetry = async (jobId: string) => {
    try {
      await retryQueueJob(jobId);
      load();
    } catch {}
  };

  const handleRetryAll = async () => {
    if (!confirm(t("admin.queueConfirmRetryAll"))) return;
    try {
      const res = await retryAllDeadJobs(domainFilter() || undefined);
      setMessage(
        t("admin.queueRetried").replace("{count}", String(res.retried)),
      );
      load();
    } catch {}
  };

  const handlePurge = async () => {
    if (!confirm(t("admin.queueConfirmPurge"))) return;
    try {
      const res = await purgeDeliveredJobs();
      setMessage(t("admin.queuePurged").replace("{count}", String(res.purged)));
      load();
    } catch {}
  };

  const totalJobPages = () => Math.max(1, Math.ceil(jobTotal() / jobLimit));
  const currentJobPage = () => Math.floor(jobOffset() / jobLimit) + 1;

  const truncateUrl = (url: string) => {
    try {
      const u = new URL(url);
      return (
        u.host + u.pathname.slice(0, 30) + (u.pathname.length > 30 ? "..." : "")
      );
    } catch {
      return url.slice(0, 50);
    }
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabQueue")}</h3>

      <Show when={stats()} fallback={<p>{t("common.loading")}</p>}>
        {(s) => (
          <>
            <div class="admin-queue-stats">
              <div class="admin-queue-stat-card pending">
                <span class="admin-queue-stat-num">{s().pending}</span>
                <span class="admin-queue-stat-label">
                  {t("admin.queuePending")}
                </span>
              </div>
              <div class="admin-queue-stat-card processing">
                <span class="admin-queue-stat-num">{s().processing}</span>
                <span class="admin-queue-stat-label">
                  {t("admin.queueProcessing")}
                </span>
              </div>
              <div class="admin-queue-stat-card delivered">
                <span class="admin-queue-stat-num">{s().delivered}</span>
                <span class="admin-queue-stat-label">
                  {t("admin.queueDelivered")}
                </span>
              </div>
              <div class="admin-queue-stat-card dead">
                <span class="admin-queue-stat-num">{s().dead}</span>
                <span class="admin-queue-stat-label">
                  {t("admin.queueDead")}
                </span>
              </div>
            </div>
            <div class="admin-queue-stats admin-queue-stats-sub">
              <div class="admin-queue-stat-card total">
                <span class="admin-queue-stat-num">{s().total}</span>
                <span class="admin-queue-stat-label">
                  {t("admin.queueTotal")}
                </span>
              </div>
              <div class="admin-queue-stat-card recent">
                <span class="admin-queue-stat-num">{s().recent_delivered}</span>
                <span class="admin-queue-stat-label">
                  {t("admin.queueRecentDelivered")}
                </span>
              </div>
              <div class="admin-queue-stat-card recent-dead">
                <span class="admin-queue-stat-num">{s().recent_dead}</span>
                <span class="admin-queue-stat-label">
                  {t("admin.queueRecentDead")}
                </span>
              </div>
            </div>
          </>
        )}
      </Show>

      <div class="admin-queue-controls">
        <h4>{t("admin.queueJobs")}</h4>
        <div class="admin-queue-filters">
          <select
            value={statusFilter()}
            onChange={(e) => {
              setStatusFilter(e.currentTarget.value);
              setJobOffset(0);
              loadJobs();
            }}
          >
            <option value="">{t("admin.queueAllStatuses")}</option>
            <option value="pending">{t("admin.queuePending")}</option>
            <option value="processing">{t("admin.queueProcessing")}</option>
            <option value="delivered">{t("admin.queueDelivered")}</option>
            <option value="dead">{t("admin.queueDead")}</option>
          </select>
          <input
            type="text"
            placeholder="Domain"
            value={domainFilter()}
            onInput={(e) => setDomainFilter(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setJobOffset(0);
                loadJobs();
              }
            }}
          />
          <button class="btn btn-small" onClick={handleRetryAll}>
            {t("admin.queueRetryAll")}
          </button>
          <button class="btn btn-small btn-danger" onClick={handlePurge}>
            {t("admin.queuePurge")}
          </button>
        </div>
      </div>

      <Show when={message()}>
        <p class="success-message">{message()}</p>
      </Show>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={jobs().length > 0}
          fallback={<p class="empty-state">{t("admin.queueNoJobs")}</p>}
        >
          <div class="admin-queue-table-wrap">
            <table class="admin-queue-table">
              <thead>
                <tr>
                  <th>{t("admin.queueTarget")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("admin.queueAttempts")}</th>
                  <th>{t("admin.queueError")}</th>
                  <th>{t("admin.queueCreated")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <For each={jobs()}>
                  {(job) => (
                    <tr class={`admin-queue-row ${job.status}`}>
                      <td
                        class="admin-queue-target"
                        title={job.target_inbox_url}
                      >
                        {truncateUrl(job.target_inbox_url)}
                      </td>
                      <td>
                        <span class={`admin-queue-badge ${job.status}`}>
                          {job.status}
                        </span>
                      </td>
                      <td>
                        {job.attempts}/{job.max_attempts}
                      </td>
                      <td
                        class="admin-queue-error"
                        title={job.error_message || ""}
                      >
                        {job.error_message
                          ? job.error_message.slice(0, 60) +
                            (job.error_message.length > 60 ? "..." : "")
                          : "-"}
                      </td>
                      <td>{new Date(job.created_at).toLocaleString()}</td>
                      <td>
                        <Show when={job.status === "dead"}>
                          <button
                            class="btn btn-small"
                            onClick={() => handleRetry(job.id)}
                          >
                            {t("admin.queueRetry")}
                          </button>
                        </Show>
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
          </div>

          <Show when={totalJobPages() > 1}>
            <div class="admin-queue-pagination">
              <button
                class="btn btn-small"
                disabled={currentJobPage() <= 1}
                onClick={() => {
                  setJobOffset(jobOffset() - jobLimit);
                  loadJobs();
                }}
              >
                &larr;
              </button>
              <span>
                {currentJobPage()} / {totalJobPages()}
              </span>
              <button
                class="btn btn-small"
                disabled={currentJobPage() >= totalJobPages()}
                onClick={() => {
                  setJobOffset(jobOffset() + jobLimit);
                  loadJobs();
                }}
              >
                &rarr;
              </button>
            </div>
          </Show>
        </Show>
      </Show>
    </div>
  );
}

function SystemTab() {
  const { t } = useI18n();
  const [stats, setStats] = createSignal<SystemStats | null>(null);

  const load = async () => {
    try {
      setStats(await getSystemStats());
    } catch {}
  };

  // 自動更新: 10秒ごと — use createEffect for reliable initialization inside Switch/Match
  let interval: ReturnType<typeof setInterval>;
  let systemInit = false;
  createEffect(() => {
    if (!systemInit) {
      systemInit = true;
      load();
      interval = setInterval(load, 10000);
    }
  });
  onCleanup(() => clearInterval(interval));

  const formatUptime = (seconds: number) => {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.tabSystem")}</h3>

      <Show when={stats()} fallback={<p>{t("common.loading")}</p>}>
        {(s) => (
          <div class="admin-system-grid">
            <div class="admin-system-card card-db">
              <h4>{t("admin.systemDatabase")}</h4>
              <div class="admin-system-rows">
                <div class="admin-system-row">
                  <span>{t("admin.systemPoolSize")}</span>
                  <strong>{s().db_pool_size}</strong>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemPoolCheckedIn")}</span>
                  <strong>{s().db_pool_checked_in}</strong>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemPoolCheckedOut")}</span>
                  <strong>{s().db_pool_checked_out}</strong>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemPoolOverflow")}</span>
                  <strong>{s().db_pool_overflow}</strong>
                </div>
              </div>
            </div>

            <div class="admin-system-card card-valkey">
              <h4>{t("admin.systemValkey")}</h4>
              <div class="admin-system-rows">
                <div class="admin-system-row">
                  <span>{t("admin.systemClients")}</span>
                  <strong>{s().valkey_connected_clients}</strong>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemMemory")}</span>
                  <strong>{s().valkey_used_memory_human}</strong>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemKeys")}</span>
                  <strong>{s().valkey_total_keys}</strong>
                </div>
              </div>
            </div>

            <div class="admin-system-card card-server">
              <h4>{t("admin.systemServer")}</h4>
              <div class="admin-system-rows">
                <div class="admin-system-row">
                  <span>{t("admin.systemLoadAvg")}</span>
                  <strong>
                    {s().load_avg_1m.toFixed(2)} / {s().load_avg_5m.toFixed(2)}{" "}
                    / {s().load_avg_15m.toFixed(2)}
                  </strong>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemMemTotal")}</span>
                  <strong>{s().memory_total_mb} MB</strong>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemMemAvailable")}</span>
                  <strong>{s().memory_available_mb} MB</strong>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemMemPercent")}</span>
                  <div class="admin-system-progress-wrap">
                    <span
                      class={`admin-system-usage ${s().memory_percent > 90 ? "critical" : s().memory_percent > 70 ? "warning" : "ok"}`}
                    >
                      <strong>{s().memory_percent.toFixed(1)}%</strong>
                    </span>
                    <div class="admin-system-progress">
                      <div
                        class={`admin-system-progress-bar ${s().memory_percent > 90 ? "critical" : s().memory_percent > 70 ? "warning" : "ok"}`}
                        style={{
                          width: `${Math.min(100, s().memory_percent)}%`,
                        }}
                      />
                    </div>
                  </div>
                </div>
                <div class="admin-system-row">
                  <span>{t("admin.systemUptime")}</span>
                  <strong>{formatUptime(s().uptime_seconds)}</strong>
                </div>
              </div>
            </div>

            <div class="admin-system-card card-worker">
              <h4>{t("admin.systemWorker")}</h4>
              <div class="admin-system-rows">
                <div class="admin-system-row">
                  <span>{t("common.status")}</span>
                  <strong>
                    <span
                      class={`admin-system-worker-status ${s().worker_alive ? "alive" : "dead"}`}
                    >
                      {s().worker_alive
                        ? t("admin.systemWorkerAlive")
                        : t("admin.systemWorkerDead")}
                    </span>
                  </strong>
                </div>
                <Show when={s().worker_last_heartbeat}>
                  <div class="admin-system-row">
                    <span>{t("admin.systemLastHeartbeat")}</span>
                    <strong>
                      {new Date(s().worker_last_heartbeat!).toLocaleString()}
                    </strong>
                  </div>
                </Show>
              </div>
            </div>
          </div>
        )}
      </Show>
    </div>
  );
}
