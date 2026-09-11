import React, { useState } from 'react';
import type { Device } from '@/lib/devices';
import { SCREENS, type ScreenId } from '@/lib/screens';
import { TRACKS } from '@/data/tracks';
import { TabIcon } from '@/components/ui';
import HomeScreen from '@/components/screens/HomeScreen';
import PlayerScreen from '@/components/screens/PlayerScreen';
import SearchScreen from '@/components/screens/SearchScreen';
import NotificationsScreen from '@/components/screens/NotificationsScreen';
import ProfileScreen from '@/components/screens/ProfileScreen';
import OnboardingScreen from '@/components/screens/OnboardingScreen';
import PaymentsScreen from '@/components/screens/PaymentsScreen';

interface Props {
  device: Device;
  screen: ScreenId;
  onScreenChange: (screen: ScreenId) => void;
}

/**
 * The "phone": a CSS bezel (390×780) with a status bar, the active screen and a
 * 7-tab bar. Must be rendered inside the SDK provider — every screen calls
 * SDK hooks.
 */
export default function PhoneFrame({ device, screen, onScreenChange }: Props) {
  const [trackId, setTrackId] = useState(TRACKS[0].id);
  const openTrack = (id: string) => {
    setTrackId(id);
    onScreenChange('player');
  };

  let body: React.ReactNode;
  switch (screen) {
    case 'home':
      body = <HomeScreen onOpenTrack={openTrack} />;
      break;
    case 'player':
      body = <PlayerScreen trackId={trackId} onChangeTrack={setTrackId} />;
      break;
    case 'search':
      body = <SearchScreen />;
      break;
    case 'notifications':
      body = <NotificationsScreen />;
      break;
    case 'profile':
      body = <ProfileScreen deviceModel={device.device_model} tier={device.tier} />;
      break;
    case 'onboarding':
      body = <OnboardingScreen />;
      break;
    case 'payments':
      body = <PaymentsScreen tier={device.tier} />;
      break;
  }

  const active = SCREENS.find((s) => s.id === screen) ?? SCREENS[0];

  return (
    <div className="phone" data-testid="phone" data-screen={screen}>
      <div className="phone-notch" aria-hidden="true" />
      <div className="phone-status" aria-hidden="true">
        <span>9:41</span>
        <span className="truncate pl-2 text-[10px] font-medium text-neutral-400">
          {device.device_model} · {device.os} {device.os_version}
        </span>
        <span>▮▮▮</span>
      </div>
      <div
        className="phone-screen"
        role="tabpanel"
        id={`screen-${active.id}`}
        aria-labelledby={`tab-${active.id}`}
        key={active.id}
        tabIndex={0}
      >
        {body}
      </div>
      <nav className="phone-tabbar" role="tablist" aria-label="StreamPulse screens">
        {SCREENS.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            id={`tab-${s.id}`}
            aria-selected={s.id === screen}
            aria-controls={`screen-${s.id}`}
            aria-label={s.name}
            className="phone-tab"
            onClick={() => onScreenChange(s.id)}
          >
            <TabIcon id={s.id} />
            <span aria-hidden="true">{s.tabLabel}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
