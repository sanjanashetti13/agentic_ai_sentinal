import { type CSSProperties } from "react";

// Fixed black overlay on the background video. 0.4 is 40%.
// The live value is `background: rgba(0, 0, 0, 0.4)` on `.scene-shade` in App.css.

// Scene motion. Durations are seconds. Change these to retune speed.
// Bird flight: birds.durations[0..3]
// Cape wind: cape.duration
// Lamp flicker: fire.duration
export const BACKGROUND_ANIMATION_CONFIG = {
  birds: {
    enabled: true,
    durations: [18, 24, 28, 21],
  },
  cape: {
    enabled: true,
    duration: 5,
  },
  fire: {
    enabled: true,
    duration: 2.5,
  },
};

function Bird({ className }: { className: string }) {
  return (
    <span className={className} aria-hidden="true">
      <svg className="scene-bird-shape" viewBox="0 0 48 20" focusable="false">
        <path className="scene-bird-wing scene-bird-wing-left" d="M24 11 C18 11 12 6 2 4 C10 9 16 11 24 11" />
        <path className="scene-bird-wing scene-bird-wing-right" d="M24 11 C30 11 36 6 46 4 C38 9 32 11 24 11" />
      </svg>
    </span>
  );
}

/**
 * landscape.jpg is one raster. The guardian, cape, wolf, crows, and lamp
 * are baked into that painting, so this layer never moves the image.
 * Birds are SVG silhouettes. Cape motion is a faint wind streak beside
 * the figure. The lamp is a small amber flicker placed over the brazier.
 */
export function SceneAtmosphere() {
  const { birds, cape, fire } = BACKGROUND_ANIMATION_CONFIG;
  const sceneStyle = {
    "--bird-1-duration": `${birds.durations[0]}s`,
    "--bird-2-duration": `${birds.durations[1]}s`,
    "--bird-3-duration": `${birds.durations[2]}s`,
    "--bird-4-duration": `${birds.durations[3]}s`,
    "--cape-duration": `${cape.duration}s`,
    "--fire-duration": `${fire.duration}s`,
  } as CSSProperties;

  return (
    <div className="scene-atmosphere" style={sceneStyle} aria-hidden="true">
      {birds.enabled ? (
        <>
          <Bird className="scene-bird scene-bird-1" />
          <Bird className="scene-bird scene-bird-2" />
          <Bird className="scene-bird scene-bird-3" />
          <Bird className="scene-bird scene-bird-4" />
        </>
      ) : null}
      {cape.enabled ? <span className="scene-wind" /> : null}
      {fire.enabled ? <span className="scene-fire" /> : null}
      <span className="scene-ember scene-ember-1" />
      <span className="scene-ember scene-ember-2" />
      <span className="scene-ember scene-ember-3" />
    </div>
  );
}
