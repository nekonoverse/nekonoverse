import { createSignal } from "solid-js";
import { apiRequest } from "../api/client";

const [followedIds, setFollowedIds] = createSignal<Set<string>>(new Set());

export { followedIds };

export async function fetchFollowedIds() {
  try {
    const ids = await apiRequest<string[]>("/api/v1/following_ids");
    setFollowedIds(new Set(ids));
  } catch {
    // 未ログインまたはエラー
  }
}

export function addFollowedId(id: string) {
  setFollowedIds((prev: Set<string>) => new Set(prev).add(id));
}

export function removeFollowedId(id: string) {
  setFollowedIds((prev: Set<string>) => {
    const next = new Set(prev);
    next.delete(id);
    return next;
  });
}

export function isFollowing(id: string): boolean {
  return followedIds().has(id);
}
