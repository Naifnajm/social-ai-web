/**
 * Solar icons (480 Design, CC BY 4.0) by semantic key: <Icon name="inbox" />, <Icon name="send" duo size={20} />.
 * Keys are listed in packages/icons/build.py (MAP). Brand logos: <PlatformIcon platform="instagram" />.
 */
import brands from "./brands.json";
import icons from "./icons.json";

type IconSet = Record<string, { linear: string; duo?: string }>;
const ICONS = icons as IconSet;

export type IconName = keyof typeof icons;

export function Icon({
  name,
  size = 18,
  duo = false,
  spin = false,
  className = "",
  title,
}: {
  name: IconName | string;
  size?: number;
  duo?: boolean;
  spin?: boolean;
  className?: string;
  title?: string;
}) {
  const entry = ICONS[name];
  if (!entry) return null;
  const body = (duo && entry.duo) || entry.linear;
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      className={`inline-block shrink-0 ${spin ? "icon-spin" : ""} ${className}`}
      dangerouslySetInnerHTML={{ __html: (title ? `<title>${title}</title>` : "") + body }}
    />
  );
}

const BRAND_PATHS = brands as Record<string, string>; // Simple Icons (CC0) + LinkedIn

export function PlatformIcon({ platform, size = 14 }: { platform: string; size?: number }) {
  const d = BRAND_PATHS[platform];
  if (!d) return null;
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden fill="currentColor">
      <path d={d} />
    </svg>
  );
}

/** Rounded brand-colour badge with the network logo. */
export function PlatformBadge({ platform, size = 26 }: { platform: string; size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-[9px] text-white"
      style={{
        width: size,
        height: size,
        background:
          platform === "instagram"
            ? "linear-gradient(45deg,#f9a825,#e1306c 45%,#833ab4)"
            : `var(--${platform}, #111)`,
      }}
      title={platform}
    >
      <PlatformIcon platform={platform} size={Math.round(size * 0.55)} />
    </span>
  );
}
