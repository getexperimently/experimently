export type ScreenId = 'home' | 'player' | 'search' | 'notifications' | 'profile' | 'onboarding' | 'payments';

export interface ScreenMeta {
  id: ScreenId;
  /** Full name, used as the accessible tab name and the screen heading. */
  name: string;
  /** Short label that fits a 7-tab bar. */
  tabLabel: string;
  /** Flag / experiment key the screen is bound to (for the story and README). */
  boundTo: string;
}

export const SCREENS: ScreenMeta[] = [
  { id: 'home', name: 'Home', tabLabel: 'Home', boundTo: 'streampulse_recs_v2' },
  { id: 'player', name: 'Player', tabLabel: 'Player', boundTo: 'streampulse_player_v2' },
  { id: 'search', name: 'Search', tabLabel: 'Search', boundTo: 'streampulse_ai_search' },
  { id: 'notifications', name: 'Notifications', tabLabel: 'Alerts', boundTo: 'streampulse_push_frequency' },
  { id: 'profile', name: 'Profile', tabLabel: 'Profile', boundTo: 'streampulse_wrapped + streampulse_profile_badges' },
  { id: 'onboarding', name: 'Onboarding', tabLabel: 'Setup', boundTo: 'streampulse_onboarding_steps' },
  { id: 'payments', name: 'Payments', tabLabel: 'Premium', boundTo: 'streampulse_upsell_modal' },
];

export const DEFAULT_SCREEN: ScreenId = 'home';

export function isScreenId(value: string): value is ScreenId {
  return SCREENS.some((s) => s.id === value);
}
