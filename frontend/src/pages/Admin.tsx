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
import { useI18n } from "@nekonoverse/ui/i18n";
import { currentUser } from "@nekonoverse/ui/stores/auth";
import { getRoleName } from "@nekonoverse/ui/api/types/auth";
import { registrationMode } from "@nekonoverse/ui/stores/instance";
import Breadcrumb from "../components/Breadcrumb";
import EmojiEditForm, {
  type EmojiEditFields,
} from "../components/reactions/EmojiEditForm";
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
  updateEmoji,
  importRemoteEmojiByShortcode,
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
  generateVapidKey,
  getModeratorPermissions,
  updateModeratorPermissions,
  getRoles,
  createRole,
  updateRole,
  deleteRole,
  type AdminRole,
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
} from "@nekonoverse/ui/api/admin";

interface AdminSection {
  key: string;
  labelKey: string;
  descKey: string;
  /** If set, moderators need this permission key to see the section. */
  permission?: string;
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
      { key: "users", labelKey: "admin.tabUsers", descKey: "admin.descUsers", permission: "users" },
      {
        key: "registrations",
        labelKey: "admin.tabRegistrations",
        descKey: "admin.descRegistrations",
        permission: "registrations",
      },
      {
        key: "domains",
        labelKey: "admin.tabDomains",
        descKey: "admin.descDomains",
        permission: "domains",
      },
      {
        key: "reports",
        labelKey: "admin.tabReports",
        descKey: "admin.descReports",
        permission: "reports",
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
        permission: "federation",
      },
      { key: "emoji", labelKey: "admin.tabEmoji", descKey: "admin.descEmoji", permission: "emoji" },
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
      { key: "files", labelKey: "admin.tabFiles", descKey: "admin.descFiles" },
      {
        key: "invites",
        labelKey: "admin.tabInvites",
        descKey: "admin.descInvites",
      },
      {
        key: "roles",
        labelKey: "admin.tabRoles",
        descKey: "admin.descRoles",
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
    const r = getRoleName(u?.role);
    return u && (r === "admin" || r === "moderator");
  };

  const isAdmin = () => getRoleName(currentUser()?.role) === "admin";

  // Fetch moderator permissions for non-admin staff to filter visible sections
  const [modPerms, setModPerms] = createSignal<Record<string, boolean> | null>(null);

  let permsInit = false;
  createEffect(() => {
    if (isStaff() && !isAdmin() && !permsInit) {
      permsInit = true;
      (async () => {
        try {
          setModPerms(await getModeratorPermissions());
        } catch {
          // If fetch fails (e.g. admin-only endpoint), show all sections
          setModPerms(null);
        }
      })();
    }
  });

  /** Check whether a section should be visible to the current user. */
  const isSectionVisible = (s: AdminSection): boolean => {
    // Registration section: only show when approval mode is active
    if (s.key === "registrations" && registrationMode() !== "approval") return false;
    // Admins can always see everything
    if (isAdmin()) return true;
    // No permission requirement means always visible to staff
    if (!s.permission) return true;
    // Moderator: check permission map
    const perms = modPerms();
    if (!perms) return true;  // Not loaded yet, show all
    return perms[s.permission] !== false;
  };

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
                          <For each={cat.sections.filter(isSectionVisible)}>
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
            <Match when={section() === "roles"}>
              <RolesTab />
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
  const [termsContent, setTermsContent] = createSignal("");
  const [privacyContent, setPrivacyContent] = createSignal("");
  const [pushEnabled, setPushEnabled] = createSignal(true);
  const [vapidKey, setVapidKey] = createSignal<string | null>(null);
  const [generatingKey, setGeneratingKey] = createSignal(false);
  const [tlDefault, setTlDefault] = createSignal(20);
  const [tlMax, setTlMax] = createSignal(40);
  const [katexEnabled, setKatexEnabled] = createSignal(false);
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
          setTermsContent(s.terms_of_service || "");
          setPrivacyContent(s.privacy_policy || "");
          setPushEnabled(s.push_enabled ?? true);
          setVapidKey(s.vapid_public_key ?? null);
          setTlDefault(s.timeline_default_limit ?? 20);
          setTlMax(s.timeline_max_limit ?? 40);
          setKatexEnabled(s.katex_enabled ?? false);
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
        terms_of_service: termsContent() || null,
        privacy_policy: privacyContent() || null,
        push_enabled: pushEnabled(),
        timeline_default_limit: tlDefault(),
        timeline_max_limit: tlMax(),
        katex_enabled: katexEnabled(),
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
          <label>{t("admin.termsOfService")}</label>
          <textarea
            rows={12}
            value={termsContent()}
            onInput={(e) => setTermsContent(e.currentTarget.value)}
            style={{ "font-family": "monospace", "font-size": "0.9em" }}
          />
        </div>
        <div class="settings-form-group">
          <label>{t("admin.privacyPolicy")}</label>
          <textarea
            rows={12}
            value={privacyContent()}
            onInput={(e) => setPrivacyContent(e.currentTarget.value)}
            style={{ "font-family": "monospace", "font-size": "0.9em" }}
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
          accept="image/jpeg,image/png,image/gif,image/webp,image/avif,image/apng,image/svg+xml"
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

      <div class="settings-section">
        <h3>{t("admin.pushSettings")}</h3>
        <div class="settings-form-group">
          <label style={{ display: "flex", "align-items": "center", gap: "8px" }}>
            <input
              type="checkbox"
              checked={pushEnabled()}
              onChange={(e) => setPushEnabled(e.currentTarget.checked)}
            />
            {t("admin.pushEnabled")}
          </label>
        </div>
        <div class="settings-form-group">
          <label>{t("admin.vapidPublicKey")}</label>
          <Show when={vapidKey()} fallback={<p style={{ color: "var(--text-muted)" }}>{t("admin.vapidNotGenerated")}</p>}>
            <input
              type="text"
              value={vapidKey()!}
              readOnly
              style={{ "font-family": "monospace", "font-size": "0.85em" }}
              onClick={(e) => e.currentTarget.select()}
            />
          </Show>
        </div>
        <button
          class="btn btn-small"
          onClick={async () => {
            if (!confirm(t("admin.vapidConfirmGenerate"))) return;
            setGeneratingKey(true);
            try {
              const res = await generateVapidKey();
              setVapidKey(res.vapid_public_key);
            } catch (e) {
              console.error("Failed to generate VAPID key:", e);
            }
            setGeneratingKey(false);
          }}
          disabled={generatingKey()}
        >
          {generatingKey() ? t("common.loading") : t("admin.vapidGenerate")}
        </button>
        <p style={{ "font-size": "0.85em", color: "var(--text-muted)", "margin-top": "8px" }}>
          {t("admin.vapidGenerateWarning")}
        </p>
      </div>

      <div class="settings-section">
        <h3>{t("admin.katexSettings")}</h3>
        <div class="settings-form-group">
          <label style={{ display: "flex", "align-items": "center", gap: "8px" }}>
            <input
              type="checkbox"
              checked={katexEnabled()}
              onChange={(e) => setKatexEnabled(e.currentTarget.checked)}
            />
            {t("admin.katexEnabled")}
          </label>
        </div>
        <button class="btn btn-small" onClick={handleSave} disabled={saving()}>
          {saving() ? t("profile.saving") : t("settings.save")}
        </button>
      </div>

      <div class="settings-section">
        <h3>{t("admin.timelineSettings")}</h3>
        <div class="settings-form-group">
          <label>{t("admin.timelineDefaultLimit")}</label>
          <input
            type="number"
            min={1}
            max={200}
            value={tlDefault()}
            onInput={(e) => setTlDefault(parseInt(e.currentTarget.value) || 20)}
            style={{ "max-width": "120px" }}
          />
        </div>
        <div class="settings-form-group">
          <label>{t("admin.timelineMaxLimit")}</label>
          <input
            type="number"
            min={1}
            max={200}
            value={tlMax()}
            onInput={(e) => setTlMax(parseInt(e.currentTarget.value) || 40)}
            style={{ "max-width": "120px" }}
          />
        </div>
        <button class="btn btn-small" onClick={handleSave} disabled={saving()}>
          {saving() ? t("profile.saving") : t("settings.save")}
        </button>
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
  const isAdmin = () => getRoleName(currentUser()?.role) === "admin";
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
                    <Show when={u.is_system} fallback={
                      <span class={`admin-role-badge role-${u.role}`}>
                        {u.role}
                      </span>
                    }>
                      <span class="admin-status-badge system">
                        {t("admin.systemAccount")}
                      </span>
                    </Show>
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
                  <Show when={!isSelf(u.id) && !u.is_system}>
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
                      <Show when={isAdmin() || (u.role !== "admin" && u.role !== "moderator")}>
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
  const [importErrors, setImportErrors] = createSignal<string[]>([]);
  const [importFileName, setImportFileName] = createSignal("");
  const [importFileSize, setImportFileSize] = createSignal("");

  // Edit modal state
  const [editTarget, setEditTarget] = createSignal<AdminEmoji | null>(null);
  const [editFields, setEditFields] = createSignal<EmojiEditFields>({
    shortcode: "", category: "", author: "", license: "", description: "", isSensitive: false, aliases: "",
  });
  const [editSaving, setEditSaving] = createSignal(false);
  const [editError, setEditError] = createSignal("");

  // Remote import modal state
  const [importTarget, setImportTarget] = createSignal<RemoteEmoji | null>(null);
  const [impFields, setImpFields] = createSignal<EmojiEditFields>({
    shortcode: "", category: "", author: "", license: "", description: "", isSensitive: false, aliases: "",
  });
  const [impSaving, setImpSaving] = createSignal(false);
  const [impError, setImpError] = createSignal("");

  // Remote emoji state
  const [remoteEmojis, setRemoteEmojis] = createSignal<RemoteEmoji[]>([]);
  const [remoteDomains, setRemoteDomains] = createSignal<string[]>([]);
  const [remoteLoading, setRemoteLoading] = createSignal(false);
  const [remoteDomain, setRemoteDomain] = createSignal("");
  const [remoteSearch, setRemoteSearch] = createSignal("");
  const [remoteMsg, setRemoteMsg] = createSignal("");
  const [importingId, setImportingId] = createSignal("");
  const [fields, setFields] = createSignal<EmojiEditFields>({
    shortcode: "",
    category: "",
    aliases: "",
    license: "",
    author: "",
    description: "",
    isSensitive: false,
  });
  const [copyPermission, setCopyPermission] = createSignal("");
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
    const f = fields();
    if (!file || !f.shortcode.trim()) return;
    setAdding(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("shortcode", f.shortcode.trim());
    if (f.category) fd.append("category", f.category);
    if (f.aliases)
      fd.append(
        "aliases",
        JSON.stringify(
          f.aliases
            .split(",")
            .map((a) => a.trim())
            .filter(Boolean),
        ),
      );
    if (f.license) fd.append("license", f.license);
    if (f.author) fd.append("author", f.author);
    if (f.description) fd.append("description", f.description);
    if (copyPermission()) fd.append("copy_permission", copyPermission());
    fd.append("is_sensitive", String(f.isSensitive));
    fd.append("local_only", String(localOnly()));
    try {
      await addEmoji(fd);
      setFields({
        shortcode: "",
        category: "",
        aliases: "",
        license: "",
        author: "",
        description: "",
        isSensitive: false,
      });
      setCopyPermission("");
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

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const handleImport = async (e: Event) => {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    setImporting(true);
    setImportMsg("");
    setImportErrors([]);
    setImportFileName(file.name);
    setImportFileSize(formatSize(file.size));
    try {
      const res = await importEmojis(file);
      setImportMsg(
        t("admin.importResult")
          .replace("{imported}", String(res.imported))
          .replace("{skipped}", String(res.skipped)),
      );
      if (res.errors && res.errors.length > 0) {
        setImportErrors(res.errors);
      }
      await load();
    } catch {
      setImportMsg("Import failed");
    }
    setImporting(false);
    (e.currentTarget as HTMLInputElement).value = "";
  };

  const openEdit = (e: AdminEmoji) => {
    setEditTarget(e);
    setEditFields({
      shortcode: e.shortcode,
      category: e.category || "",
      author: e.author || "",
      license: e.license || "",
      description: e.description || "",
      isSensitive: e.is_sensitive,
      aliases: (e.aliases || []).join(", "),
    });
    setEditError("");
  };

  const handleEditSave = async () => {
    const target = editTarget();
    if (!target || editSaving()) return;
    setEditSaving(true);
    setEditError("");
    try {
      const f = editFields();
      await updateEmoji(target.id, {
        shortcode: f.shortcode !== target.shortcode ? f.shortcode : undefined,
        category: f.category || undefined,
        author: f.author || undefined,
        license: f.license || undefined,
        description: f.description || undefined,
        is_sensitive: f.isSensitive,
        aliases: f.aliases
          ? f.aliases.split(",").map((s) => s.trim()).filter(Boolean)
          : [],
      });
      setEditTarget(null);
      await load();
    } catch (e: any) {
      setEditError(e.message || "Failed to save");
    } finally {
      setEditSaving(false);
    }
  };

  const openImportModal = (e: RemoteEmoji) => {
    setImportTarget(e);
    setImpFields({
      shortcode: e.shortcode,
      category: e.category || "",
      author: e.author || "",
      license: e.license || "",
      description: e.description || "",
      isSensitive: e.is_sensitive,
      aliases: (e.aliases || []).join(", "),
    });
    setImpError("");
  };

  const handleImportSave = async () => {
    const target = importTarget();
    if (!target || !target.domain || impSaving()) return;
    setImpSaving(true);
    setImpError("");
    try {
      const f = impFields();
      await importRemoteEmojiByShortcode({
        shortcode: target.shortcode,
        domain: target.domain,
        shortcode_override: f.shortcode !== target.shortcode ? f.shortcode : undefined,
        category: f.category || undefined,
        author: f.author || undefined,
        license: f.license || undefined,
        description: f.description || undefined,
        is_sensitive: f.isSensitive,
        aliases: f.aliases
          ? f.aliases.split(",").map((s) => s.trim()).filter(Boolean)
          : undefined,
      });
      setImportTarget(null);
      setRemoteMsg(t("admin.importSuccess"));
      await load();
      await loadRemote();
    } catch (e: any) {
      setImpError(e.message || t("admin.importFailed"));
    } finally {
      setImpSaving(false);
    }
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
      <Show when={importErrors().length > 0}>
        <details class="import-errors">
          <summary class="settings-error">{importErrors().length} errors</summary>
          <ul>
            {importErrors().map((err) => <li>{err}</li>)}
          </ul>
        </details>
      </Show>

      <Show when={showForm()}>
        <div class="admin-emoji-form">
          <div class="settings-form-group">
            <label>{t("admin.emojiFile")}</label>
            <input ref={fileInput} type="file" accept="image/*" />
          </div>
          <EmojiEditForm
            fields={fields()}
            onChange={setFields}
            showAdminFields
            copyPermission={copyPermission()}
            onCopyPermissionChange={setCopyPermission}
            localOnly={localOnly()}
            onLocalOnlyChange={setLocalOnly}
          />
          <button
            class="btn btn-small"
            onClick={handleAdd}
            disabled={adding() || !fields().shortcode.trim()}
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
                    class="btn btn-small"
                    onClick={() => openEdit(e)}
                  >
                    {t("admin.editEmoji")}
                  </button>
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
                  onClick={() => openImportModal(e)}
                  disabled={e.copy_permission === "deny"}
                >
                  {t("admin.importEmoji")}
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

      {/* Edit local emoji modal */}
      <Show when={editTarget()}>
        <div class="modal-overlay" onClick={() => setEditTarget(null)}>
          <div class="modal-content" style="max-width: 440px" onClick={(e) => e.stopPropagation()}>
            <div class="modal-header">
              <h3 style="display: flex; align-items: center; gap: 8px">
                <img src={editTarget()!.url} alt={editTarget()!.shortcode} style="height: 32px" />
                {t("admin.editEmoji")}
              </h3>
              <button class="modal-close" onClick={() => setEditTarget(null)}>✕</button>
            </div>
            <div class="emoji-import-form">
              <EmojiEditForm
                fields={editFields()}
                onChange={setEditFields}
              />
              <Show when={editError()}>
                <div class="emoji-import-error">{editError()}</div>
              </Show>
              <div class="emoji-import-actions">
                <button class="btn" onClick={() => setEditTarget(null)}>
                  {t("common.cancel")}
                </button>
                <button class="btn btn-primary" onClick={handleEditSave} disabled={editSaving()}>
                  {editSaving() ? t("common.loading") : t("settings.save")}
                </button>
              </div>
            </div>
          </div>
        </div>
      </Show>

      {/* Import remote emoji modal */}
      <Show when={importTarget()}>
        <div class="modal-overlay" onClick={() => setImportTarget(null)}>
          <div class="modal-content" style="max-width: 440px" onClick={(e) => e.stopPropagation()}>
            <div class="modal-header">
              <h3 style="display: flex; align-items: center; gap: 8px">
                <img src={importTarget()!.url} alt={importTarget()!.shortcode} style="height: 32px" />
                {t("admin.importEmoji")}
              </h3>
              <button class="modal-close" onClick={() => setImportTarget(null)}>✕</button>
            </div>
            <div class="emoji-import-form">
              <EmojiEditForm
                fields={impFields()}
                onChange={setImpFields}
                previewUrl={importTarget()!.url}
                previewDomain={importTarget()!.domain}
              />
              <Show when={impError()}>
                <div class="emoji-import-error">{impError()}</div>
              </Show>
              <div class="emoji-import-actions">
                <button class="btn" onClick={() => setImportTarget(null)}>
                  {t("common.cancel")}
                </button>
                <button class="btn btn-primary" onClick={handleImportSave} disabled={impSaving()}>
                  {impSaving() ? t("common.loading") : t("admin.importEmoji")}
                </button>
              </div>
            </div>
          </div>
        </div>
      </Show>

      {/* ZIP import progress modal */}
      <Show when={importing()}>
        <div class="modal-overlay">
          <div class="modal-content emoji-import-progress">
            <div class="emoji-import-spinner" />
            <p class="emoji-import-title">{t("admin.importingEmoji" as any)}</p>
            <p class="emoji-import-detail">{importFileName()} ({importFileSize()})</p>
          </div>
        </div>
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

  // Domain action state
  const [domainAction, setDomainAction] = createSignal<{
    type: "suspend" | "silence";
    domain: string;
  } | null>(null);
  const [domainConfirmInput, setDomainConfirmInput] = createSignal("");
  const [domainActionReason, setDomainActionReason] = createSignal("");
  const [domainActionLoading, setDomainActionLoading] = createSignal(false);

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

  const openDomainAction = (type: "suspend" | "silence", domain: string) => {
    setDomainConfirmInput("");
    setDomainActionReason("");
    setDomainAction({ type, domain });
  };

  const closeDomainAction = () => {
    setDomainAction(null);
    setDomainConfirmInput("");
    setDomainActionReason("");
    setDomainActionLoading(false);
  };

  const executeDomainAction = async () => {
    const action = domainAction();
    if (!action) return;
    setDomainActionLoading(true);
    try {
      // If escalating from silence to suspend, remove existing block first
      const currentServer = servers().find((s) => s.domain === action.domain);
      if (currentServer?.block_severity && currentServer.block_severity !== action.type) {
        await removeDomainBlock(action.domain);
      }
      await createDomainBlock(action.domain, action.type, domainActionReason() || undefined);
      closeDomainAction();
      await load();
      // Refresh detail if expanded
      if (expandedDomain() === action.domain) {
        setDetail(await getFederatedServerDetail(action.domain));
      }
    } catch {
      setDomainActionLoading(false);
    }
  };

  const domainConfirmMatches = () => {
    const action = domainAction();
    if (!action) return false;
    return domainConfirmInput() === action.domain;
  };

  const handleRemoveDomainBlock = async (domain: string) => {
    try {
      await removeDomainBlock(domain);
      await load();
      // Refresh detail if expanded
      if (expandedDomain() === domain) {
        setDetail(await getFederatedServerDetail(domain));
      }
    } catch {}
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
    <>
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
                                    <div class="admin-federation-actions" style="margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap;">
                                      <Show when={d().block_severity === "suspend"}>
                                        <button
                                          class="btn btn-small"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            handleRemoveDomainBlock(d().domain);
                                          }}
                                        >
                                          {t("admin.federationUnsuspendDomain")}
                                        </button>
                                      </Show>
                                      <Show when={d().block_severity === "silence"}>
                                        <button
                                          class="btn btn-small"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            handleRemoveDomainBlock(d().domain);
                                          }}
                                        >
                                          {t("admin.federationUnsilenceDomain")}
                                        </button>
                                      </Show>
                                      <Show when={d().block_severity !== "suspend"}>
                                        <button
                                          class="btn btn-small btn-danger"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            openDomainAction("suspend", d().domain);
                                          }}
                                        >
                                          {t("admin.federationSuspendDomain")}
                                        </button>
                                      </Show>
                                      <Show when={!d().block_severity}>
                                        <button
                                          class="btn btn-small btn-danger"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            openDomainAction("silence", d().domain);
                                          }}
                                        >
                                          {t("admin.federationSilenceDomain")}
                                        </button>
                                      </Show>
                                    </div>
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
                &larr;
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
                &rarr;
              </button>
            </div>
          </Show>
        </Show>
      </Show>
    </div>

      {/* Confirmation modal for domain suspend/silence */}
      <Show when={domainAction()}>
        {(action) => (
          <div class="modal-overlay" onClick={closeDomainAction}>
            <div
              class="modal-content"
              style="max-width: 420px"
              onClick={(e) => e.stopPropagation()}
            >
              <div class="modal-header">
                <h3>
                  {action().type === "suspend"
                    ? t("admin.federationConfirmSuspendTitle")
                    : t("admin.federationConfirmSilenceTitle")}
                </h3>
                <button class="modal-close" onClick={closeDomainAction}>
                  ✕
                </button>
              </div>
              <div style="padding: 16px">
                <p class="confirm-input-hint">
                  {t("admin.federationTypeDomainToConfirm").replace(
                    "{domain}",
                    action().domain,
                  )}
                </p>
                <input
                  class="confirm-input"
                  type="text"
                  value={domainConfirmInput()}
                  onInput={(e) => setDomainConfirmInput(e.currentTarget.value)}
                  placeholder={action().domain}
                  autofocus
                />
                <input
                  class="confirm-input"
                  type="text"
                  value={domainActionReason()}
                  onInput={(e) => setDomainActionReason(e.currentTarget.value)}
                  placeholder={t("admin.federationReasonPlaceholder")}
                  style="margin-top: 8px"
                />
                <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px">
                  <button class="btn btn-small" onClick={closeDomainAction}>
                    {t("common.cancel")}
                  </button>
                  <button
                    class="btn btn-small btn-danger"
                    disabled={!domainConfirmMatches() || domainActionLoading()}
                    onClick={executeDomainAction}
                  >
                    {action().type === "suspend"
                      ? t("admin.federationSuspendDomain")
                      : t("admin.federationSilenceDomain")}
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

const PERMISSION_KEYS = [
  "users",
  "reports",
  "content",
  "domains",
  "federation",
  "emoji",
  "registrations",
] as const;

const PERM_LABEL_KEYS: Record<string, string> = {
  users: "admin.permUsers",
  reports: "admin.permReports",
  content: "admin.permContent",
  domains: "admin.permDomains",
  federation: "admin.permFederation",
  emoji: "admin.permEmoji",
  registrations: "admin.permRegistrations",
};

const PERM_DESC_KEYS: Record<string, string> = {
  users: "admin.permUsersDesc",
  reports: "admin.permReportsDesc",
  content: "admin.permContentDesc",
  domains: "admin.permDomainsDesc",
  federation: "admin.permFederationDesc",
  emoji: "admin.permEmojiDesc",
  registrations: "admin.permRegistrationsDesc",
};

function formatQuota(bytes: number): string {
  if (bytes === 0) return "Unlimited";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function RolesTab() {
  const { t } = useI18n();
  const [roles, setRoles] = createSignal<AdminRole[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal("");
  const [saved, setSaved] = createSignal(false);
  const [editingRole, setEditingRole] = createSignal<string | null>(null);
  const [editData, setEditData] = createSignal<{
    display_name: string;
    permissions: Record<string, boolean>;
    quota_bytes: number;
    priority: number;
  } | null>(null);
  const [showCreate, setShowCreate] = createSignal(false);
  const [newName, setNewName] = createSignal("");
  const [newDisplayName, setNewDisplayName] = createSignal("");
  const [copyFrom, setCopyFrom] = createSignal("");

  const loadRoles = async () => {
    try {
      setRoles(await getRoles());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load roles");
    }
    setLoading(false);
  };

  let init = false;
  createEffect(() => {
    if (!init) {
      init = true;
      loadRoles();
    }
  });

  const startEdit = (role: AdminRole) => {
    setEditingRole(role.name);
    setEditData({
      display_name: role.display_name,
      permissions: { ...role.permissions },
      quota_bytes: role.quota_bytes,
      priority: role.priority,
    });
    setSaved(false);
  };

  const cancelEdit = () => {
    setEditingRole(null);
    setEditData(null);
  };

  const handleSave = async () => {
    const name = editingRole();
    const data = editData();
    if (!name || !data) return;
    setError("");
    setSaved(false);
    try {
      await updateRole(name, data);
      await loadRoles();
      setSaved(true);
      setEditingRole(null);
      setEditData(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    }
  };

  const handleCreate = async () => {
    const name = newName().trim();
    const displayName = newDisplayName().trim();
    if (!name || !displayName) return;
    setError("");
    try {
      await createRole({
        name,
        display_name: displayName,
        copy_from: copyFrom() || undefined,
      });
      await loadRoles();
      setShowCreate(false);
      setNewName("");
      setNewDisplayName("");
      setCopyFrom("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create role");
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(t("admin.roleConfirmDelete" as any))) return;
    setError("");
    try {
      await deleteRole(name);
      await loadRoles();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete role");
    }
  };

  const togglePermission = (key: string) => {
    const data = editData();
    if (!data) return;
    setEditData({
      ...data,
      permissions: { ...data.permissions, [key]: !data.permissions[key] },
    });
  };

  return (
    <div class="settings-section">
      <h3>{t("admin.rolesTitle" as any)}</h3>
      <p style={{ color: "var(--text-muted)", "margin-bottom": "16px" }}>
        {t("admin.rolesDesc" as any)}
      </p>
      <Show when={error()}>
        <p class="error">{error()}</p>
      </Show>
      <Show when={saved()}>
        <p class="settings-success">{t("settings.saved")}</p>
      </Show>
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <div style={{ display: "flex", "flex-direction": "column", gap: "12px" }}>
          <For each={roles()}>
            {(role) => (
              <div class="admin-role-card" style={{
                border: "1px solid var(--border-color)",
                "border-radius": "8px",
                padding: "16px",
              }}>
                <div style={{
                  display: "flex",
                  "justify-content": "space-between",
                  "align-items": "center",
                  "margin-bottom": editingRole() === role.name ? "12px" : "0",
                }}>
                  <div>
                    <strong>{role.display_name}</strong>
                    <span style={{
                      color: "var(--text-muted)",
                      "margin-left": "8px",
                      "font-size": "0.9em",
                    }}>
                      ({role.name})
                    </span>
                    <Show when={role.is_admin}>
                      <span style={{
                        "margin-left": "8px",
                        color: "var(--accent)",
                        "font-size": "0.85em",
                      }}>Admin</span>
                    </Show>
                  </div>
                  <div style={{ display: "flex", gap: "8px", "align-items": "center" }}>
                    <span style={{ color: "var(--text-muted)", "font-size": "0.85em" }}>
                      {t("admin.roleQuota" as any)}: {role.quota_bytes === 0
                        ? t("admin.roleUnlimited" as any)
                        : formatQuota(role.quota_bytes)}
                    </span>
                    <Show when={editingRole() !== role.name}>
                      <button class="btn btn-small" onClick={() => startEdit(role)}>
                        {t("settings.edit" as any)}
                      </button>
                    </Show>
                    <Show when={!role.is_system}>
                      <button
                        class="btn btn-small btn-danger"
                        onClick={() => handleDelete(role.name)}
                      >
                        {t("admin.roleDelete" as any)}
                      </button>
                    </Show>
                  </div>
                </div>
                <Show when={editingRole() === role.name && editData()}>
                  {(data) => (
                    <div style={{ "border-top": "1px solid var(--border-color)", "padding-top": "12px" }}>
                      <div style={{ "margin-bottom": "12px" }}>
                        <label style={{ display: "block", "margin-bottom": "4px", "font-size": "0.9em" }}>
                          {t("admin.roleDisplayName" as any)}
                        </label>
                        <input
                          type="text"
                          class="input"
                          value={data().display_name}
                          onInput={(e) => setEditData({ ...data(), display_name: e.currentTarget.value })}
                          style={{ width: "200px" }}
                        />
                      </div>
                      <div style={{ "margin-bottom": "12px" }}>
                        <label style={{ display: "block", "margin-bottom": "4px", "font-size": "0.9em" }}>
                          {t("admin.roleQuota" as any)} (MB, 0 = {t("admin.roleUnlimited" as any)})
                        </label>
                        <input
                          type="number"
                          class="input"
                          value={data().quota_bytes / (1024 * 1024)}
                          onInput={(e) => setEditData({
                            ...data(),
                            quota_bytes: Math.max(0, parseInt(e.currentTarget.value) || 0) * 1024 * 1024,
                          })}
                          style={{ width: "120px" }}
                          min="0"
                        />
                      </div>
                      <div style={{ "margin-bottom": "12px" }}>
                        <label style={{ display: "block", "margin-bottom": "4px", "font-size": "0.9em" }}>
                          {t("admin.rolePriority" as any)}
                        </label>
                        <input
                          type="number"
                          class="input"
                          value={data().priority}
                          onInput={(e) => setEditData({
                            ...data(),
                            priority: parseInt(e.currentTarget.value) || 0,
                          })}
                          style={{ width: "80px" }}
                        />
                      </div>
                      <Show when={!role.is_admin}>
                        <div style={{ "margin-bottom": "12px" }}>
                          <label style={{ display: "block", "margin-bottom": "8px", "font-size": "0.9em" }}>
                            {t("admin.permissionsTitle" as any)}
                          </label>
                          <div class="admin-permissions-list">
                            <For each={[...PERMISSION_KEYS]}>
                              {(key) => (
                                <div class="admin-permissions-item">
                                  <div class="admin-permissions-info">
                                    <strong>{t(PERM_LABEL_KEYS[key] as any)}</strong>
                                    <span style={{ color: "var(--text-muted)", "font-size": "0.9em" }}>
                                      {t(PERM_DESC_KEYS[key] as any)}
                                    </span>
                                  </div>
                                  <label class="admin-permissions-toggle">
                                    <input
                                      type="checkbox"
                                      checked={data().permissions[key] !== false && data().permissions[key] !== undefined
                                        ? true : !!data().permissions[key]}
                                      onChange={() => togglePermission(key)}
                                    />
                                    <span class="admin-permissions-slider" />
                                  </label>
                                </div>
                              )}
                            </For>
                          </div>
                        </div>
                      </Show>
                      <div style={{ display: "flex", gap: "8px" }}>
                        <button class="btn btn-small" onClick={handleSave}>
                          {t("settings.save")}
                        </button>
                        <button class="btn btn-small" onClick={cancelEdit}>
                          {t("common.cancel" as any)}
                        </button>
                      </div>
                    </div>
                  )}
                </Show>
              </div>
            )}
          </For>
        </div>

        <div style={{ "margin-top": "16px" }}>
          <Show when={!showCreate()}>
            <button class="btn btn-small" onClick={() => setShowCreate(true)}>
              {t("admin.roleCreate" as any)}
            </button>
          </Show>
          <Show when={showCreate()}>
            <div style={{
              border: "1px solid var(--border-color)",
              "border-radius": "8px",
              padding: "16px",
            }}>
              <div style={{ "margin-bottom": "12px" }}>
                <label style={{ display: "block", "margin-bottom": "4px", "font-size": "0.9em" }}>
                  {t("admin.roleName" as any)} (a-z, 0-9, _)
                </label>
                <input
                  type="text"
                  class="input"
                  value={newName()}
                  onInput={(e) => setNewName(e.currentTarget.value)}
                  style={{ width: "200px" }}
                  placeholder="custom_role"
                />
              </div>
              <div style={{ "margin-bottom": "12px" }}>
                <label style={{ display: "block", "margin-bottom": "4px", "font-size": "0.9em" }}>
                  {t("admin.roleDisplayName" as any)}
                </label>
                <input
                  type="text"
                  class="input"
                  value={newDisplayName()}
                  onInput={(e) => setNewDisplayName(e.currentTarget.value)}
                  style={{ width: "200px" }}
                />
              </div>
              <div style={{ "margin-bottom": "12px" }}>
                <label style={{ display: "block", "margin-bottom": "4px", "font-size": "0.9em" }}>
                  {t("admin.roleCopyFrom" as any)}
                </label>
                <select
                  class="input"
                  value={copyFrom()}
                  onChange={(e) => setCopyFrom(e.currentTarget.value)}
                  style={{ width: "200px" }}
                >
                  <option value="">---</option>
                  <For each={roles()}>
                    {(r) => <option value={r.name}>{r.display_name}</option>}
                  </For>
                </select>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button class="btn btn-small" onClick={handleCreate}>
                  {t("admin.roleCreate" as any)}
                </button>
                <button class="btn btn-small" onClick={() => setShowCreate(false)}>
                  {t("common.cancel" as any)}
                </button>
              </div>
            </div>
          </Show>
        </div>
      </Show>
    </div>
  );
}
