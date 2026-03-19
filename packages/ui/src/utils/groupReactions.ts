import type { ReactionSummary } from "../api/statuses";
import { hammingDistance, PHASH_THRESHOLD } from "./phash";

export interface GroupedReaction {
  displayEmoji: string;
  displayUrl: string | null;
  count: number;
  me: boolean;
  myEmoji: string | null;
  importable: boolean;
  importDomain: string | null;
  members: ReactionSummary[];
}

function isCustomEmoji(emoji: string): boolean {
  return emoji.startsWith(":") && emoji.endsWith(":");
}

function isLocalEmoji(emoji: string): boolean {
  return !emoji.includes("@");
}

export function groupReactions(
  reactions: ReactionSummary[],
  hashMap: ReadonlyMap<string, string>,
): GroupedReaction[] {
  const groups: GroupedReaction[] = [];
  const hashToGroupIndex = new Map<string, number>();

  for (const r of reactions) {
    if (!isCustomEmoji(r.emoji)) {
      const existing = groups.find((g) => g.displayEmoji === r.emoji);
      if (existing) {
        mergeInto(existing, r);
      } else {
        groups.push(createGroup(r));
      }
      continue;
    }

    if (!r.emoji_url) {
      groups.push(createGroup(r));
      continue;
    }

    const hash = hashMap.get(r.emoji_url);

    if (!hash) {
      groups.push(createGroup(r));
      continue;
    }

    let matched = false;
    for (const [existingHash, groupIdx] of hashToGroupIndex) {
      if (hammingDistance(hash, existingHash) <= PHASH_THRESHOLD) {
        mergeInto(groups[groupIdx], r);
        matched = true;
        break;
      }
    }

    if (!matched) {
      hashToGroupIndex.set(hash, groups.length);
      groups.push(createGroup(r));
    }
  }

  return groups;
}

function createGroup(r: ReactionSummary): GroupedReaction {
  return {
    displayEmoji: r.emoji,
    displayUrl: r.emoji_url,
    count: r.count,
    me: r.me,
    myEmoji: r.me ? r.emoji : null,
    importable: r.importable ?? false,
    importDomain: r.import_domain ?? null,
    members: [r],
  };
}

function mergeInto(group: GroupedReaction, r: ReactionSummary): void {
  group.count += r.count;
  group.members.push(r);

  if (r.me) {
    group.me = true;
    group.myEmoji = r.emoji;
  }

  if (isCustomEmoji(r.emoji) && isLocalEmoji(r.emoji)) {
    group.displayEmoji = r.emoji;
    group.displayUrl = r.emoji_url;
    group.importable = false;
    group.importDomain = null;
  }

  if (
    r.importable &&
    !group.members.some((m) => isCustomEmoji(m.emoji) && isLocalEmoji(m.emoji))
  ) {
    group.importable = true;
    group.importDomain = r.import_domain ?? group.importDomain;
  }
}
