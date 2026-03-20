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

const SHORTCODE_RE = /^:([a-zA-Z0-9_]+)(?:@[^:]+)?:$/;

export function extractShortcode(emoji: string): string | null {
  const m = SHORTCODE_RE.exec(emoji);
  return m ? m[1] : null;
}

export function groupReactions(
  reactions: ReactionSummary[],
  hashMap: ReadonlyMap<string, string>,
): GroupedReaction[] {
  const groups: GroupedReaction[] = [];
  const shortcodeToIdx = new Map<string, number>();
  const unicodeToIdx = new Map<string, number>();

  // Phase 1: shortcode-based grouping (O(n))
  // Unicode emoji → exact match, custom emoji → shortcode match
  for (const r of reactions) {
    if (!isCustomEmoji(r.emoji)) {
      const idx = unicodeToIdx.get(r.emoji);
      if (idx !== undefined) {
        mergeInto(groups[idx], r);
      } else {
        unicodeToIdx.set(r.emoji, groups.length);
        groups.push(createGroup(r));
      }
      continue;
    }

    const sc = extractShortcode(r.emoji);
    if (sc) {
      const idx = shortcodeToIdx.get(sc);
      if (idx !== undefined) {
        mergeInto(groups[idx], r);
        continue;
      }
      shortcodeToIdx.set(sc, groups.length);
    }
    groups.push(createGroup(r));
  }

  // Phase 2: phash-based merging across different shortcodes (O(G²) on groups)
  const hashToIdx = new Map<string, number>();
  for (let i = 0; i < groups.length; i++) {
    const g = groups[i];
    if (!g || !isCustomEmoji(g.displayEmoji) || !g.displayUrl) continue;
    const hash = hashMap.get(g.displayUrl);
    if (!hash) continue;

    let merged = false;
    for (const [existingHash, existingIdx] of hashToIdx) {
      if (existingIdx !== i && hammingDistance(hash, existingHash) <= PHASH_THRESHOLD) {
        const target = groups[existingIdx];
        target.count += g.count;
        target.members.push(...g.members);
        if (g.me) {
          target.me = true;
          target.myEmoji = g.myEmoji;
        }
        if (isLocalEmoji(g.displayEmoji)) {
          target.displayEmoji = g.displayEmoji;
          target.displayUrl = g.displayUrl;
          target.importable = false;
          target.importDomain = null;
        }
        if (
          g.importable &&
          !target.members.some((m) => isCustomEmoji(m.emoji) && isLocalEmoji(m.emoji))
        ) {
          target.importable = true;
          target.importDomain = g.importDomain;
        }
        (groups as any)[i] = null;
        merged = true;
        break;
      }
    }
    if (!merged) {
      hashToIdx.set(hash, i);
    }
  }

  return groups.filter((g): g is GroupedReaction => g !== null);
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
