export interface CustomEmoji {
  shortcode: string;
  url: string;
  static_url: string;
}

export interface RecentEmoji {
  emoji: string;       // Unicode char or ":shortcode:"
  isCustom: boolean;
  url?: string;
  shortcode?: string;  // For display/search without colons
}
