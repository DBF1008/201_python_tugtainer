import { TagSeverity } from '@shared/types/tag-severity.type';
import { IContainerInspectResult } from '../../features/containers/containers.interface';
import { IImageInspectResult } from '../../features/images/images.interface';

/**
 * Result of container check
 */
export type TContainerCheckResult =
  | 'not_available'
  | 'available'
  | 'available(notified)'
  | 'updated'
  | 'rolled_back'
  | 'failed'
  | null;

export interface IContainerActionResult {
  container: IContainerInspectResult;
  result: TContainerCheckResult;
  image_spec: string | null;
  local_image: IImageInspectResult | null;
  remote_image: IImageInspectResult | null;
  local_digests: string[];
  remote_digests: string[];
}

export interface IUpdatePlanResult {
  host_id: number;
  host_name: string;
  items: IContainerActionResult[];
}

/**
 * Terminal outcome of a host's check/update action.
 * Lets consumers tell apart success / skipped / failed.
 */
export enum EHostActionStatus {
  SUCCESS = 'success',
  SKIPPED = 'skipped',
  FAILED = 'failed',
}

export interface IHostActionResult extends IUpdatePlanResult {
  prune_result: string | null;
  status: EHostActionStatus;
  error: string | null;
}

export const ContainerCheckResultSeverity: Record<
  TContainerCheckResult,
  TagSeverity
> = {
  'available': 'success',
  'available(notified)': 'success',
  'updated': 'info',
  'not_available': 'contrast',
  'rolled_back': 'warn',
  'failed': 'danger',
};

export const HostActionStatusSeverity: Record<EHostActionStatus, TagSeverity> =
  {
    [EHostActionStatus.SUCCESS]: 'success',
    [EHostActionStatus.SKIPPED]: 'secondary',
    [EHostActionStatus.FAILED]: 'danger',
  };
