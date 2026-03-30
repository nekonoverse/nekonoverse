import { createSignal, onMount, Show, For } from "solid-js";
import { getDriveFiles, type DriveFile } from "@nekonoverse/ui/api/drive";
import { useI18n } from "@nekonoverse/ui/i18n";

interface Props {
  onSelect: (files: DriveFile[]) => void;
  onClose: () => void;
  maxSelect: number;
}

export default function DrivePicker(props: Props) {
  const { t } = useI18n();
  const [files, setFiles] = createSignal<DriveFile[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [selected, setSelected] = createSignal<Set<string>>(new Set());
  const [hasMore, setHasMore] = createSignal(true);
  const [loadingMore, setLoadingMore] = createSignal(false);

  const PAGE_SIZE = 24;

  onMount(async () => {
    try {
      const data = await getDriveFiles(PAGE_SIZE, 0);
      setFiles(data);
      setHasMore(data.length >= PAGE_SIZE);
    } catch {}
    setLoading(false);
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

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < props.maxSelect) {
        next.add(id);
      }
      return next;
    });
  };

  const handleConfirm = () => {
    const sel = selected();
    const chosen = files().filter((f) => sel.has(f.id));
    props.onSelect(chosen);
  };

  return (
    <div class="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) props.onClose(); }}>
      <div class="modal-content drive-picker-modal">
        <div class="modal-header">
          <h3>{t("drive.pickFromDrive")}</h3>
          <button class="modal-close" onClick={props.onClose}>✕</button>
        </div>
        <Show when={!loading()} fallback={<p class="modal-loading">{t("common.loading")}</p>}>
          <Show when={files().length > 0} fallback={<p class="empty">{t("drive.empty")}</p>}>
            <div class="drive-picker-grid">
              <For each={files()}>
                {(file) => (
                  <div
                    class={`drive-picker-item${selected().has(file.id) ? " selected" : ""}`}
                    onClick={() => toggleSelect(file.id)}
                  >
                    <img src={file.thumbnail_url || file.url} alt={file.description || file.filename} loading="lazy" />
                    <Show when={selected().has(file.id)}>
                      <div class="drive-picker-check">✓</div>
                    </Show>
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
        <div class="modal-footer">
          <span class="drive-picker-count">{selected().size} / {props.maxSelect}</span>
          <button class="btn btn-small" onClick={handleConfirm} disabled={selected().size === 0}>
            {t("drive.select")}
          </button>
        </div>
      </div>
    </div>
  );
}
