export interface IVersion {
  image_version: string;
}

export interface IsUpdateAvailableResponseBody {
  is_available: boolean;
  release_url: string;
}

export interface IHostSummary {
  host_id: number;
  host_name: string;
  host_enabled: boolean;
  total_containers: number;
  by_status: Record<string, number>;
  by_health: Record<string, number>;
  by_protected: Record<string, number>;
  by_check_enabled: Record<string, number>;
  by_update_enabled: Record<string, number>;
  by_update_available: Record<string, number>;
  total_images: number;
  unused_images: number;
  dangling_images: number;
  /**
   * Set when the host could not be reached/queried. Statistic fields are
   * zeroed in that case; healthy hosts still return their real data.
   */
  error?: string | null;
}
