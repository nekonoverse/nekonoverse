import { createSignal, onMount, Show, For } from "solid-js";
import { getDriveFiles, deleteDriveFile, type DriveFile } from "@nekonoverse/ui/api/drive";
import { uploadMedia } from "@nekonoverse/ui/api/statuses";
import { getAccountStorage, type StorageInfo } from "@nekonoverse/ui/api/admin";
import { useI18n } from "@nekonoverse/ui/i18n";
import { currentUser } from "@nekonoverse/ui/stores/auth";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export default function Drive() {
  const { t } = useI18n();
  const [files, setFiles] = createSignal<DriveFile[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [uploading, setUploading] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [storage, setStorage] = createSignal<StorageInfo | null>(null);

  let fileInput!: HTMLInputElement;

  const PAGE_SIZE = 20;

  const loadStorage = async () => {
    try {
      setStorage(await getAccountStorage());
    } catch {}
  };

  const load = async () => {
    try {
      const data = await getDriveFiles(PAGE_SIZE, 0);
      setFiles(data);
      setHasMore(data.length >= PAGE_SIZE);
    } catch {}
    setLoading(false);
  };

  onMount(() => {
    load();
    loadStorage();
  });

  const loadMore = async () => {
    if (loadingMore()) return;
    setLoadingMore(true);
    try {
      const data = await getDriveFiles(PAGE_SIZE, files().length);
      setFiles((prev) => [...prev, ...data]);
      setHasMore(data.length >= PAGE_SIZE);
    } catch {}
    setLoadingMore(false);
  };

  const handleUpload = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    setUploading(true);
    for (const file of Array.from(fileList)) {
      try {
        await uploadMedia(file);
      } catch {}
    }
    setUploading(false);
    if (fileInput) fileInput.value = "";
    await load();
    await loadStorage();
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("drive.confirmDelete"))) return;
    try {
      await deleteDriveFile(id);
      setFiles((prev) => prev.filter((f) => f.id !== id));
      await loadStorage();
    } catch {}
  };

  const quotaExceeded = () => {
    const s = storage();
    return s && s.quota_bytes > 0 && s.usage_percent >= 100;
  };

  return (
    <div class="page-container drive-page">
      <div class="drive-header">
        <h2>{t("drive.title")}</h2>
        <Show when={currentUser()}>
          <button
            class="btn btn-small"
            onClick={() => fileInput.click()}
            disabled={uploading() || quotaExceeded()}
          >
            {uploading() ? t("common.loading") : t("drive.upload")}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            multiple
            onChange={(e) => handleUpload(e.currentTarget.files)}
            style="display: none"
          />
        </Show>
      </div>

      <Show when={storage()}>
        {(s) => (
          <div class="drive-quota-bar" style={{ "margin-bottom": "16px" }}>
            <div style={{
              display: "flex",
              "justify-content": "space-between",
              "font-size": "0.9em",
              "margin-bottom": "4px",
            }}>
              <span>
                {t("drive.storageUsed" as any)}: {formatSize(s().usage_bytes)}
                {" "}{t("drive.storageOf" as any)}{" "}
                {s().quota_bytes === 0
                  ? t("drive.storageUnlimited" as any)
                  : formatSize(s().quota_bytes)}
              </span>
              <Show when={s().quota_bytes > 0}>
                <span>{s().usage_percent}%</span>
              </Show>
            </div>
            <Show when={s().quota_bytes > 0}>
              <div style={{
                width: "100%",
                height: "8px",
                "background-color": "var(--bg-secondary)",
                "border-radius": "4px",
                overflow: "hidden",
              }}>
                <div style={{
                  width: `${Math.min(100, s().usage_percent)}%`,
                  height: "100%",
                  "background-color": s().usage_percent >= 90
                    ? "var(--error, #e74c3c)"
                    : "var(--accent)",
                  "border-radius": "4px",
                  transition: "width 0.3s ease",
                }} />
              </div>
            </Show>
            <Show when={quotaExceeded()}>
              <p style={{ color: "var(--error, #e74c3c)", "font-size": "0.85em", "margin-top": "4px" }}>
                {t("drive.quotaExceeded" as any)}
              </p>
            </Show>
          </div>
        )}
      </Show>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={currentUser()} fallback={<p>{t("drive.loginRequired")}</p>}>
          <Show when={files().length > 0} fallback={<p class="empty">{t("drive.empty")}</p>}>
            <div class="drive-grid">
              <For each={files()}>
                {(file) => (
                  <div class="drive-item">
                    <a href={file.url} target="_blank" rel="noopener" class="drive-thumb">
                      <img src={file.url} alt={file.description || file.filename} loading="lazy" />
                    </a>
                    <div class="drive-item-info">
                      <span class="drive-filename" title={file.filename}>{file.filename}</span>
                      <span class="drive-meta">{formatSize(file.size_bytes)}</span>
                    </div>
                    <button class="drive-delete-btn" onClick={() => handleDelete(file.id)} title={t("drive.delete")}>
                      ✕
                    </button>
                  </div>
                )}
              </For>
            </div>
            <Show when={hasMore()}>
              <div class="load-more">
                <button class="btn btn-small" onClick={loadMore} disabled={loadingMore()}>
                  {loadingMore() ? t("common.loading") : t("notifications.loadMore")}
                </button>
              </div>
            </Show>
          </Show>
        </Show>
      </Show>
    </div>
  );
}
