import type { ActivityFilters } from "@aec/types/activity";

export const activityKeys = {
  all: ["activity"] as const,
  feeds: () => [...activityKeys.all, "feed"] as const,
  feed: (filters: ActivityFilters) =>
    [...activityKeys.feeds(), filters] as const,
};
