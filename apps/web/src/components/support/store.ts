/**
 * What the app remembers about the last failed request, and the "write to support" dialog.
 *
 *   noteFailure({...})                called by the API client on every failed request
 *   recentFailure()                   the failure of the last few seconds (attached to an error toast)
 *   useSupport.getState().show(f)     open the dialog, with a failure attached or not
 */
import { create } from "zustand";

export type Failure = {
  message: string; code: string; status: number; ref?: string | null; request: string; page: string; at: number;
};

let last: Failure | null = null;

export function noteFailure(failure: Omit<Failure, "at" | "page">) {
  last = { ...failure, page: typeof window === "undefined" ? "" : window.location.pathname, at: Date.now() };
}

/** The failure that just happened, if any: a toast shown right after it is about it. */
export function recentFailure(withinMs = 4000): Failure | null {
  return last && Date.now() - last.at < withinMs ? last : null;
}

export const useSupport = create<{
  enabled: boolean; open: boolean; failure: Failure | null;
  show: (failure?: Failure | null) => void; hide: () => void;
}>((set) => ({
  enabled: false, open: false, failure: null,
  show: (failure = null) => set({ open: true, failure }),
  hide: () => set({ open: false, failure: null }),
}));
