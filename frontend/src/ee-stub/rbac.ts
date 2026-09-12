/**
 * Community stub for `@ee/rbac`.
 *
 * Same exported shape as `src/ee/rbac.ts` so every caller type-checks in both
 * editions, but every method rejects. It deliberately does **not** return an
 * empty list: "no custom roles" and "custom roles are not in this build" are
 * different facts, and a UI that shows the first when the second is true is
 * lying. Gate the call site with `useFeature(FEATURES.RBAC)` instead — the
 * throw is the backstop for a caller that forgot.
 */
import { CustomRole } from '@/types/admin';
import { FEATURES } from '@/services/edition';

export interface CreateRoleRequest {
  name: string;
  description: string;
  permissions: string[];
}

export interface UserPermissionsResponse {
  permissions: string[];
}

/** Thrown by every stubbed Enterprise call. */
export class FeatureNotLicensedError extends Error {
  readonly feature: string;

  constructor(feature: string) {
    super(`"${feature}" is an Enterprise feature and is not available in this build`);
    this.name = 'FeatureNotLicensedError';
    this.feature = feature;
    Object.setPrototypeOf(this, FeatureNotLicensedError.prototype);
  }
}

function unlicensed(): never {
  throw new FeatureNotLicensedError(FEATURES.RBAC);
}

export const RbacService = {
  async listRoles(): Promise<CustomRole[]> {
    return unlicensed();
  },

  async createRole(data: CreateRoleRequest): Promise<CustomRole> {
    return unlicensed();
  },

  async updateRole(name: string, data: Partial<CustomRole>): Promise<CustomRole> {
    return unlicensed();
  },

  async deleteRole(name: string): Promise<void> {
    return unlicensed();
  },

  async getUserPermissions(userId: string): Promise<UserPermissionsResponse> {
    return unlicensed();
  },
};

export default RbacService;
