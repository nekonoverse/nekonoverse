import { createSignal, onMount, Show, For } from "solid-js";
import { getDriveFiles, deleteDriveFile, type DriveFile } from "../api/drive";
import { uploadMedia } from "../api/statuses";
import { useI18n } from "../i18n";
import { currentUser } from "../stores/auth";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Drive() {
  const { t } = useI18n();
  const [files, setFiles] = createSignal<DriveFile[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [uploading, setUploading] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);
  const [loadingMore, setLoadingMore] = createSignal(false);

  let fileInput!: HTMLInputElement;

  const PAGE_SIZE = 20;

  const load = async () => {
    try {
      const data = await getDriveFiles(PAGE_SIZE, 0);
      setFiles(data);
      setHasMore(data.length >= PAGE_SIZE);
    } catch {}
    setLoading(false);
  };

  onMount(load);

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
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("drive.confirmDelete"))) return;
    try {
      await deleteDriveFile(id);
      setFiles((prev) => prev.filter((f) => f.id !== id));
    } catch {}
  };

  return (
    <div class="page-container drive-page">
      <div class="drive-header">
        <h2>{t("drive.title")}</h2>
        <Show when={currentUser()}>
          <button
            class="btn btn-small"
            onClick={() => fileInput.click()}
            disabled={uploading()}
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
