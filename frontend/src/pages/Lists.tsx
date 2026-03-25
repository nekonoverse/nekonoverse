import { createSignal, createResource, Show, For, onCleanup } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { getLists, createList, updateList, deleteList, type ListInfo } from "@nekonoverse/ui/api/lists";
import { currentUser, authLoading } from "@nekonoverse/ui/stores/auth";
import { useI18n } from "@nekonoverse/ui/i18n";

export default function Lists() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [lists, setLists] = createSignal<ListInfo[]>([]);
  const [creating, setCreating] = createSignal(false);
  const [editingId, setEditingId] = createSignal<string | null>(null);
  const [title, setTitle] = createSignal("");
  const [repliesPolicy, setRepliesPolicy] = createSignal("list");
  const [exclusive, setExclusive] = createSignal(false);

  const [initialData] = createResource(
    () => (!authLoading() && currentUser() ? true : false),
    async () => {
      const data = await getLists();
      setLists(data);
      return data;
    },
  );

  const handleCreate = async () => {
    if (!title().trim()) return;
    const lst = await createList(title().trim(), repliesPolicy(), exclusive());
    setLists((prev) => [...prev, lst]);
    setTitle("");
    setRepliesPolicy("list");
    setExclusive(false);
    setCreating(false);
  };

  const handleUpdate = async (id: string) => {
    if (!title().trim()) return;
    const updated = await updateList(id, {
      title: title().trim(),
      replies_policy: repliesPolicy(),
      exclusive: exclusive(),
    });
    setLists((prev) => prev.map((l) => (l.id === id ? updated : l)));
    setEditingId(null);
    setTitle("");
    setRepliesPolicy("list");
    setExclusive(false);
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("list.confirmDelete"))) return;
    await deleteList(id);
    setLists((prev) => prev.filter((l) => l.id !== id));
  };

  const startEdit = (lst: ListInfo) => {
    setEditingId(lst.id);
    setTitle(lst.title);
    setRepliesPolicy(lst.replies_policy);
    setExclusive(lst.exclusive);
    setCreating(false);
  };

  const startCreate = () => {
    setCreating(true);
    setEditingId(null);
    setTitle("");
    setRepliesPolicy("list");
    setExclusive(false);
  };

  const cancelForm = () => {
    setCreating(false);
    setEditingId(null);
    setTitle("");
    setRepliesPolicy("list");
    setExclusive(false);
  };

  const repliesPolicyLabel = (policy: string) => {
    switch (policy) {
      case "none": return t("list.repliesNone");
      case "list": return t("list.repliesList");
      case "followed": return t("list.repliesFollowed");
      default: return policy;
    }
  };

  return (
    <div class="page-container">
      <div class="lists-header">
        <h1>{t("list.title")}</h1>
        <Show when={currentUser() && !creating() && !editingId()}>
          <button class="btn btn-primary" onClick={startCreate}>
            {t("list.create")}
          </button>
        </Show>
      </div>
      <Show when={!authLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={currentUser()} fallback={<p>{t("list.loginRequired")}</p>}>
          {/* Create / Edit form */}
          <Show when={creating() || editingId()}>
            <div class="list-form">
              <input
                type="text"
                class="input"
                placeholder={t("list.nameLabel")}
                value={title()}
                onInput={(e) => setTitle(e.currentTarget.value)}
                maxLength={200}
              />
              <div class="list-form-options">
                <label class="list-form-label">
                  {t("list.repliesPolicy")}
                  <select
                    class="select"
                    value={repliesPolicy()}
                    onChange={(e) => setRepliesPolicy(e.currentTarget.value)}
                  >
                    <option value="list">{t("list.repliesList")}</option>
                    <option value="followed">{t("list.repliesFollowed")}</option>
                    <option value="none">{t("list.repliesNone")}</option>
                  </select>
                </label>
                <label class="list-form-checkbox">
                  <input
                    type="checkbox"
                    checked={exclusive()}
                    onChange={(e) => setExclusive(e.currentTarget.checked)}
                  />
                  {t("list.exclusive")}
                </label>
              </div>
              <div class="list-form-actions">
                <Show when={creating()}>
                  <button class="btn btn-primary" onClick={handleCreate}>
                    {t("list.create")}
                  </button>
                </Show>
                <Show when={editingId()}>
                  <button class="btn btn-primary" onClick={() => handleUpdate(editingId()!)}>
                    {t("list.save")}
                  </button>
                </Show>
                <button class="btn" onClick={cancelForm}>
                  {t("list.cancel")}
                </button>
              </div>
            </div>
          </Show>

          <Show when={initialData.state === "ready"} fallback={<p>{t("common.loading")}</p>}>
            <Show when={lists().length > 0} fallback={<p class="empty">{t("list.empty")}</p>}>
              <div class="lists-grid">
                <For each={lists()}>
                  {(lst) => (
                    <div class="list-card" onClick={() => navigate(`/lists/${lst.id}`)}>
                      <div class="list-card-title">{lst.title}</div>
                      <div class="list-card-meta">
                        <span class="list-card-badge">{repliesPolicyLabel(lst.replies_policy)}</span>
                        <Show when={lst.exclusive}>
                          <span class="list-card-badge list-card-badge-exclusive">{t("list.exclusive")}</span>
                        </Show>
                      </div>
                      <div class="list-card-actions" onClick={(e) => e.stopPropagation()}>
                        <button class="btn btn-small" onClick={() => startEdit(lst)}>
                          {t("list.edit")}
                        </button>
                        <button class="btn btn-small btn-danger" onClick={() => handleDelete(lst.id)}>
                          {t("list.delete")}
                        </button>
                      </div>
                    </div>
                  )}
                </For>
              </div>
            </Show>
          </Show>
        </Show>
      </Show>
    </div>
  );
}
