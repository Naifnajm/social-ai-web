/**
 * Session store: tokens, the signed-in user, their workspaces and the active one (with the user's role in it).
 *
 *   const { status, me, workspace, role } = useSession();
 *   can('approver');  await signIn(email, password);  await switchWorkspace(id);  await signOut();
 */
import { useSyncExternalStore } from 'react';

import { api, clearTokens, loadTokens, saveTokens, setApiWorkspace, setOnUnauthenticated } from './api';
import { getLocale } from './i18n';
import { KEYS, getItem, setItem } from './storage';
import type { Me, Role, SessionOut, Workspace } from './types';

type State = {
  status: 'loading' | 'signedOut' | 'signedIn';
  me: Me | null;
  workspace: Workspace | null;
  role: Role;
};

const RANK: Record<Role, number> = { viewer: 0, editor: 1, approver: 2, admin: 3, owner: 4 };

let state: State = { status: 'loading', me: null, workspace: null, role: 'viewer' };
const listeners = new Set<() => void>();
const signOutHooks = new Set<() => Promise<void> | void>();
const signInHooks = new Set<() => Promise<void> | void>();

function set(patch: Partial<State>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

export function getSession(): State {
  return state;
}

export function can(role: Role): boolean {
  return RANK[state.role] >= RANK[role];
}

/** Run something after every sign-in (push registration) / before every sign-out (push unregistration). */
export function onSignedIn(hook: () => Promise<void> | void) {
  signInHooks.add(hook);
  return () => signInHooks.delete(hook);
}
export function onSigningOut(hook: () => Promise<void> | void) {
  signOutHooks.add(hook);
  return () => signOutHooks.delete(hook);
}

async function loadWorkspace(me: Me) {
  const remembered = Number(await getItem(KEYS.workspace)) || null;
  const id = me.workspaces.some((w) => w.workspace_id === remembered) ? remembered : me.current_workspace_id;
  setApiWorkspace(id);
  const data = await api.get<{ workspace: Workspace; role: Role }>('/workspace');
  setApiWorkspace(data.workspace.id);
  await setItem(KEYS.workspace, String(data.workspace.id));
  set({ me, workspace: data.workspace, role: data.role, status: 'signedIn' });
}

async function startSession(session: SessionOut) {
  await saveTokens(session);
  await loadWorkspace(session.me);
  signInHooks.forEach((h) => void Promise.resolve(h()).catch(() => undefined));
}

/** App start: restore the stored session (refreshing the access token when needed). */
export async function bootstrap(): Promise<void> {
  setOnUnauthenticated(() => void signOut({ remote: false }));
  try {
    if (!(await loadTokens())) {
      set({ status: 'signedOut' });
      return;
    }
    const me = await api.get<Me>('/auth/me');
    await loadWorkspace(me);
    signInHooks.forEach((h) => void Promise.resolve(h()).catch(() => undefined));
  } catch {
    // offline or expired: if tokens are still stored keep the user out only when they are invalid
    if (state.status !== 'signedIn') set({ status: 'signedOut' });
  }
}

export async function signIn(email: string, password: string): Promise<void> {
  const session = await api.post<SessionOut>('/auth/login', { email: email.trim(), password });
  await startSession(session);
}

export async function signUp(data: { name: string; email: string; password: string; workspace_name: string }): Promise<void> {
  const session = await api.post<SessionOut>('/auth/signup', { ...data, email: data.email.trim(), locale: getLocale() });
  await startSession(session);
}

export async function signOut({ remote = true }: { remote?: boolean } = {}): Promise<void> {
  if (state.status === 'signedOut') return;
  if (remote) {
    for (const hook of signOutHooks) {
      try {
        await hook();
      } catch {
        /* best effort */
      }
    }
    try {
      await api.post('/auth/logout');
    } catch {
      /* offline */
    }
  }
  await clearTokens();
  setApiWorkspace(null);
  set({ status: 'signedOut', me: null, workspace: null, role: 'viewer' });
}

export async function switchWorkspace(id: number): Promise<void> {
  if (!state.me) return;
  await setItem(KEYS.workspace, String(id));
  await loadWorkspace(state.me);
}

export async function reloadMe(): Promise<void> {
  const me = await api.get<Me>('/auth/me');
  set({ me });
}

export async function createWorkspace(name: string): Promise<void> {
  const ws = await api.post<Workspace>('/workspaces', { name });
  const me = await api.get<Me>('/auth/me');
  await setItem(KEYS.workspace, String(ws.id));
  await loadWorkspace(me);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useSession(): State & { can: (role: Role) => boolean } {
  const s = useSyncExternalStore(subscribe, getSession, getSession);
  return { ...s, can: (role: Role) => RANK[s.role] >= RANK[role] };
}
