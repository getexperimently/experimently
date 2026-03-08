import { type Page, type Locator } from "@playwright/test";
import { CommonPage } from "./common.page";

/**
 * Page object for admin panel pages (user management, audit log, settings).
 */
export class AdminPage {
  readonly page: Page;
  readonly common: CommonPage;

  // Navigation tabs
  readonly usersTab: Locator;
  readonly auditLogTab: Locator;
  readonly settingsTab: Locator;

  // User management
  readonly userList: Locator;
  readonly createUserButton: Locator;
  readonly userRoleSelect: Locator;
  readonly userSearchInput: Locator;

  // Audit log
  readonly auditLogTable: Locator;
  readonly auditLogFilter: Locator;
  readonly auditLogDateRange: Locator;

  // Settings
  readonly settingsForm: Locator;
  readonly saveSettingsButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.common = new CommonPage(page);

    // Tabs
    this.usersTab = page.locator(
      'a:has-text("Users"), button:has-text("Users"), [role="tab"]:has-text("Users")'
    );
    this.auditLogTab = page.locator(
      'a:has-text("Audit"), button:has-text("Audit"), [role="tab"]:has-text("Audit")'
    );
    this.settingsTab = page.locator(
      'a:has-text("Settings"), button:has-text("Settings"), [role="tab"]:has-text("Settings")'
    );

    // User management
    this.userList = page.locator(
      '[class*="user-list"], table, [class*="list"]'
    );
    this.createUserButton = page.locator(
      'button:has-text("Add User"), button:has-text("Create User"), button:has-text("Invite")'
    );
    this.userRoleSelect = page.locator(
      'select[name*="role"], [class*="role-select"]'
    );
    this.userSearchInput = page.locator(
      'input[placeholder*="search" i]'
    );

    // Audit log
    this.auditLogTable = page.locator(
      'table:near(:text("Audit")), [class*="audit-log"]'
    );
    this.auditLogFilter = page.locator(
      'select[name*="action"], [class*="filter"]'
    );
    this.auditLogDateRange = page.locator(
      'input[type="date"], [class*="date-range"]'
    );

    // Settings
    this.settingsForm = page.locator('form, [class*="settings"]');
    this.saveSettingsButton = page.locator(
      'button:has-text("Save"), button[type="submit"]'
    );
  }

  async goto() {
    await this.common.navigateTo("/admin");
  }

  async gotoUsers() {
    await this.goto();
    const tabVisible = await this.usersTab.isVisible().catch(() => false);
    if (tabVisible) {
      await this.usersTab.click();
      await this.common.waitForPageReady();
    }
  }

  async gotoAuditLog() {
    await this.goto();
    const tabVisible = await this.auditLogTab.isVisible().catch(() => false);
    if (tabVisible) {
      await this.auditLogTab.click();
      await this.common.waitForPageReady();
    }
  }

  async gotoSettings() {
    await this.goto();
    const tabVisible = await this.settingsTab.isVisible().catch(() => false);
    if (tabVisible) {
      await this.settingsTab.click();
      await this.common.waitForPageReady();
    }
  }

  async getUserCount(): Promise<number> {
    const rows = this.userList.locator("tr, [class*='row']");
    return rows.count();
  }

  async searchUsers(query: string) {
    await this.userSearchInput.fill(query);
    await this.common.waitForPageReady();
  }

  async getAuditLogEntryCount(): Promise<number> {
    const rows = this.auditLogTable.locator("tr, [class*='row']");
    return rows.count();
  }
}
