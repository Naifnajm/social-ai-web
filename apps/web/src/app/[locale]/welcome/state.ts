/** Shared, mutable animation state read every frame by the 3D scene (kept out of React on purpose). */
export const motionState = {
  /** 0 → 1 while the hero scrolls out of view. */
  hero: 0,
  /** performance.now() when the hero intro started, -1 before. */
  introAt: -1,
};
